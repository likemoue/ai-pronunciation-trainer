"""Admission control: a worker holds a bounded number of recordings and texts to
synthesise, and answers the next ones at once with 503 and Retry-After."""
import json
import logging

import pytest

import lambdaSpeechToScore
import piperTTS
from conftest import make_audio, requires_ffmpeg


def test_the_queue_takes_up_to_its_limit():
    queue = lambdaSpeechToScore.ScoringQueue(limit=3, max_wait=1000, initial_seconds=2.0)
    assert [queue.admit() for _ in range(3)] == [0, 1, 2]
    with pytest.raises(lambdaSpeechToScore.ServerBusyError) as busy:
        queue.admit()
    assert busy.value.retry_after == 6  # three recordings ahead, 2 s each
    queue.release()
    assert queue.admit() == 2
    assert queue.pending == 3


def test_the_queue_turns_away_a_wait_longer_than_max_wait():
    queue = lambdaSpeechToScore.ScoringQueue(limit=100, max_wait=30, initial_seconds=8.0)
    for _ in range(4):
        queue.admit()  # 4 ahead x 8 s = 32 s > 30 s for the next one
    with pytest.raises(lambdaSpeechToScore.ServerBusyError) as busy:
        queue.admit()
    assert busy.value.retry_after == 30  # capped


def test_retry_after_is_at_least_a_second():
    queue = lambdaSpeechToScore.ScoringQueue(limit=0, max_wait=30, initial_seconds=0.1)
    with pytest.raises(lambdaSpeechToScore.ServerBusyError) as busy:
        queue.admit()
    assert busy.value.retry_after == 1


def test_a_class_right_after_a_start_fits_the_limit():
    # 20 ahead at the 1 s guess is 20 s, under max_wait: the limit decides.
    queue = lambdaSpeechToScore.ScoringQueue(limit=20, max_wait=30)
    assert [queue.admit() for _ in range(20)][-1] == 19
    with pytest.raises(lambdaSpeechToScore.ServerBusyError) as busy:
        queue.admit()
    assert busy.value.retry_after == 20


@requires_ffmpeg
def test_the_warm_up_neither_queues_nor_counts(fake_asr, monkeypatch):
    # A worker that restarts while learners fill its queue must still warm up
    # (or it never becomes ready), and a cold model's first pass must not make
    # the queue think every recording takes that long.
    queue = lambdaSpeechToScore.ScoringQueue(limit=1, max_wait=30, initial_seconds=1.0)
    monkeypatch.setattr(lambdaSpeechToScore, '_queue', queue)
    monkeypatch.setattr(lambdaSpeechToScore, '_warm_languages', set())
    queue.admit()  # a learner's recording holds the only place
    lambdaSpeechToScore.score('Hello world', make_audio('webm', seconds=1.0), 'en', warm_up=True)
    assert queue.pending == 1 and queue.seconds_per_recording == 1.0
    queue.release()
    lambdaSpeechToScore.score('Hello world', make_audio('webm', seconds=1.0), 'en')
    assert queue.pending == 0 and queue.seconds_per_recording != 1.0


@requires_ffmpeg
def test_a_cold_first_pass_does_not_count_whoever_takes_it(fake_asr, monkeypatch):
    # On a worker that restarts while learners record, a learner's recording
    # can reach the model before the warm-up and pay its first pass (about
    # 15 s); timing it turned the next class burst away for 30 s.
    queue = lambdaSpeechToScore.ScoringQueue(limit=5, max_wait=30, initial_seconds=1.0)
    monkeypatch.setattr(lambdaSpeechToScore, '_queue', queue)
    monkeypatch.setattr(lambdaSpeechToScore, '_warm_languages', set())
    audio = make_audio('webm', seconds=1.0)
    # Nothing heard: the word alignment did not run, so the model is still cold.
    fake_asr.transcript = ''
    with pytest.raises(lambdaSpeechToScore.NoSpeechError):
        lambdaSpeechToScore.score('Hello world', audio, 'en')
    fake_asr.transcript = 'Hello world'
    lambdaSpeechToScore.score('Hello world', audio, 'en')
    assert queue.seconds_per_recording == 1.0
    lambdaSpeechToScore.score('Hello world', audio, 'en')
    assert queue.seconds_per_recording != 1.0 and queue.pending == 0


def test_the_queue_learns_how_long_a_recording_takes():
    queue = lambdaSpeechToScore.ScoringQueue(limit=5, max_wait=30, initial_seconds=2.0)
    for _ in range(40):
        queue.admit()
        queue.release(held_seconds=0.5)
    assert queue.seconds_per_recording == pytest.approx(0.5, abs=0.01)
    queue.admit()
    queue.release()  # no measurement (an upload that failed to decode)
    assert queue.seconds_per_recording == pytest.approx(0.5, abs=0.01)
    assert queue.pending == 0


@pytest.mark.parametrize('environ,limit', [
    ({}, 20), ({'GUNICORN_THREADS': '8'}, 4), ({'GUNICORN_THREADS': '2'}, 1),
    ({'SCORING_QUEUE_LIMIT': '3', 'GUNICORN_THREADS': '24'}, 3), ({'SCORING_QUEUE_LIMIT': '0'}, 1),
])
def test_the_limit_leaves_threads_for_other_requests(environ, limit):
    assert lambdaSpeechToScore._queue_limit(environ) == limit


def _score_request(client, text='Hello world'):
    import base64
    audio = base64.b64encode(make_audio('webm', seconds=1.0)).decode()
    return client.post('/GetAccuracyFromRecordedAudio', json={
        'title': text, 'base64Audio': 'data:audio/webm;base64,' + audio, 'language': 'en'})


@requires_ffmpeg
def test_a_full_worker_answers_503_with_retry_after(client, fake_asr, monkeypatch, caplog):
    queue = lambdaSpeechToScore.ScoringQueue(limit=2, max_wait=30, initial_seconds=1.5)
    queue.admit()
    queue.admit()
    monkeypatch.setattr(lambdaSpeechToScore, '_queue', queue)
    with caplog.at_level(logging.INFO, logger='aipt.lambdaSpeechToScore'):
        response = _score_request(client)
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '3'
    body = response.get_json()
    assert body['code'] == 'busy' and body['retry_after'] == 3
    assert queue.pending == 2  # the refused recording took no place
    scored = [r for r in caplog.records if r.getMessage() == 'scored']
    assert scored and scored[-1].fields['outcome'] == 'busy' and 'decode_ms' not in scored[-1].fields


@requires_ffmpeg
def test_a_scored_recording_gives_its_place_back(client, fake_asr, monkeypatch):
    queue = lambdaSpeechToScore.ScoringQueue(limit=1, max_wait=30)
    monkeypatch.setattr(lambdaSpeechToScore, '_queue', queue)
    for _ in range(3):
        assert _score_request(client).status_code == 200
    assert queue.pending == 0


@requires_ffmpeg
def test_a_failed_recording_gives_its_place_back(client, fake_asr, monkeypatch):
    queue = lambdaSpeechToScore.ScoringQueue(limit=1, max_wait=30)
    monkeypatch.setattr(lambdaSpeechToScore, '_queue', queue)
    response = client.post('/GetAccuracyFromRecordedAudio', json={
        'title': 'Hello', 'base64Audio': 'data:audio/webm;base64,AAAA' + 'A' * 2000, 'language': 'en'})
    assert response.status_code == 400
    fake_asr.transcript = ''
    assert _score_request(client).status_code == 422
    assert queue.pending == 0


@requires_ffmpeg
def test_a_recording_whose_client_left_is_not_scored(fake_asr, monkeypatch):
    calls = []
    monkeypatch.setattr(fake_asr, 'processAudio', lambda audio: calls.append(audio))
    with pytest.raises(lambdaSpeechToScore.ClientGoneError):
        lambdaSpeechToScore.score('Hello world', make_audio('webm', seconds=1.0), 'en', client_gone=lambda: True)
    assert calls == []
    assert lambdaSpeechToScore._queue.pending == 0


@requires_ffmpeg
def test_a_recording_whose_client_waits_is_scored(fake_asr):
    result = lambdaSpeechToScore.score('Hello world', make_audio('webm', seconds=1.0), 'en',
                                       client_gone=lambda: False)
    assert result['pronunciation_accuracy'] == '100'


def test_the_client_gone_check_reads_the_socket():
    import socket
    import webApp
    if not hasattr(__import__('select'), 'poll'):
        pytest.skip('select.poll is not available on this platform')
    server, client_sock = socket.socketpair()
    try:
        with webApp.app.test_request_context(environ_base={'gunicorn.socket': server}):
            gone = webApp._client_gone_check()
            assert gone() is False  # open and idle
            client_sock.sendall(b'x')
            assert gone() is False  # data waiting is not a close
            server.recv(1)
            client_sock.close()
            assert gone() is True  # closed by the other side
    finally:
        server.close()


def test_outside_gunicorn_there_is_no_client_gone_check():
    import webApp
    with webApp.app.test_request_context():
        assert webApp._client_gone_check() is None


def test_a_busy_voice_answers_503_and_the_browser_reads_the_text(client, fake_voice, monkeypatch):
    monkeypatch.setattr(piperTTS, '_synth_pending', piperTTS._SYNTH_QUEUE_LIMIT)
    response = client.post('/getAudioFromText', json={'value': 'Hello there', 'language': 'en'})
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '2'
    assert response.get_json()['code'] == 'tts_busy'
    assert fake_voice.synthesized == []


def test_a_cached_text_is_read_even_when_the_voice_is_busy(client, fake_voice, monkeypatch):
    assert client.post('/getAudioFromText', json={'value': 'Hello there', 'language': 'en'}).status_code == 200
    monkeypatch.setattr(piperTTS, '_synth_pending', piperTTS._SYNTH_QUEUE_LIMIT)
    assert client.post('/getAudioFromText', json={'value': 'Hello there', 'language': 'en'}).status_code == 200


def test_synthesis_gives_its_place_back(client, fake_voice):
    for n in range(5):
        assert client.post('/getAudioFromText', json={'value': f'Hello there {n}', 'language': 'en'}).status_code == 200
    assert piperTTS._synth_pending == 0


def test_the_busy_answer_is_json(client, fake_voice, monkeypatch):
    monkeypatch.setattr(piperTTS, '_synth_pending', piperTTS._SYNTH_QUEUE_LIMIT)
    response = client.post('/getAudioFromText', json={'value': 'Hello', 'language': 'en'})
    assert response.mimetype == 'application/json'
    json.loads(response.data)
