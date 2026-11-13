"""API contract and abuse regression tests.

Each attack in this file was reproduced against the previous version, where it
pinned a worker, allocated gigabytes of memory or ran for minutes. Every one
must now get a fast 4xx JSON answer.
"""
import base64
import io
import json
import time
import wave

import numpy as np
import pytest

from conftest import make_audio, requires_ffmpeg

API_ROUTES = ['/getSample', '/getCustomSample', '/GetAccuracyFromRecordedAudio', '/getAudioFromText']


def data_url(raw: bytes, mime='audio/webm') -> str:
    return f'data:{mime};base64,' + base64.b64encode(raw).decode()


def score(client, title, raw_audio, mime='audio/webm'):
    return client.post('/GetAccuracyFromRecordedAudio',
                       json={'title': title, 'base64Audio': data_url(raw_audio, mime), 'language': 'en'})


def assert_json_error(response, status, code=None):
    assert response.status_code == status, response.get_data(as_text=True)
    assert response.mimetype == 'application/json'
    body = response.get_json()
    assert body['error']
    if code:
        assert body['code'] == code


# ------------------------------------------------------------------ /getSample

@pytest.mark.parametrize('category', [4, -1, 99, 'abc', None, True, 1.5, [1], {'a': 1}])
def test_get_sample_rejects_unknown_category_quickly(client, category):
    start = time.perf_counter()
    response = client.post('/getSample', json={'category': category, 'language': 'en'})
    assert_json_error(response, 400, 'bad_category')
    assert time.perf_counter() - start < 2


def test_get_sample_rejects_missing_category(client):
    assert_json_error(client.post('/getSample', json={'language': 'en'}), 400, 'bad_category')


@pytest.mark.parametrize('category,low,high', [(1, 0, 8), (2, 8, 20), (3, 20, 10 ** 6), (0, 0, 10 ** 6)])
@pytest.mark.parametrize('as_string', [False, True])
def test_get_sample_respects_category(client, category, low, high, as_string):
    for _ in range(25):
        value = str(category) if as_string else category
        response = client.post('/getSample', json={'category': value, 'language': 'en'})
        assert response.status_code == 200
        assert response.mimetype == 'application/json'
        sentence = response.get_json()['real_transcript'][0]
        assert low < len(sentence.split()) <= high


def test_get_sample_rejects_disabled_language(client):
    assert_json_error(client.post('/getSample', json={'category': 1, 'language': 'de'}), 400, 'bad_language')


# ------------------------------------------------------------------ request format

@pytest.mark.parametrize('path', API_ROUTES)
def test_cross_site_form_post_is_rejected(client, path):
    # An HTML form can send text/plain without a CORS preflight; the old
    # get_json(force=True) parsed it anyway.
    response = client.post(path, data='{"category": 1, "title": "x", "value": "x"}',
                           content_type='text/plain')
    assert_json_error(response, 415)


@pytest.mark.parametrize('path', API_ROUTES)
def test_body_must_be_a_json_object(client, path):
    assert_json_error(client.post(path, json=[1, 2, 3]), 400)


def test_oversized_body_is_rejected(client):
    body = json.dumps({'title': 'Hello world', 'language': 'en', 'base64Audio': 'A' * (5 * 1024 * 1024)})
    response = client.post('/GetAccuracyFromRecordedAudio', data=body, content_type='application/json')
    assert_json_error(response, 413)


def test_errors_are_json(client):
    assert_json_error(client.get('/no-such-page'), 404)
    assert_json_error(client.get('/getSample'), 405)


def test_no_cors_headers(client):
    response = client.post('/getSample', json={'category': 1, 'language': 'en'},
                           headers={'Origin': 'https://evil.example'})
    assert 'Access-Control-Allow-Origin' not in response.headers


def test_security_headers(client):
    response = client.get('/')
    assert response.status_code == 200
    csp = response.headers['Content-Security-Policy']
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'microphone=(self)' in response.headers['Permissions-Policy']
    assert response.headers['Referrer-Policy']
    assert response.headers['X-Request-ID']


def test_request_id_reuses_cloudflare_ray_id(client):
    response = client.get('/', headers={'CF-Ray': 'a59c8cf62e459010-SIN'})
    assert response.headers['X-Request-ID'] == 'a59c8cf62e459010-SIN'


def test_page_has_no_inline_styles_or_scripts(client):
    html = client.get('/').get_data(as_text=True)
    assert 'style="' not in html
    assert '<script>' not in html


# ------------------------------------------------------------------ text limits

def test_scoring_rejects_long_title_before_decoding(client, fake_asr):
    start = time.perf_counter()
    response = score(client, 'word ' * 3000, b'not even audio')
    assert_json_error(response, 400, 'text_too_long')
    assert time.perf_counter() - start < 1


@pytest.mark.parametrize('title', ['你好世界', 'Xin chào các bạn học sinh thân mến', '   ', '- ... -'])
def test_scoring_rejects_unusable_titles(client, fake_asr, title):
    assert_json_error(score(client, title, b'x'), 400)


@pytest.mark.parametrize('text', ['你' * 600, 'Привет, как дела у тебя сегодня?', 'a ' * 200, ''])
def test_tts_rejects_unusable_text_without_synthesis(client, text):
    start = time.perf_counter()
    response = client.post('/getAudioFromText', json={'value': text, 'language': 'en'})
    assert_json_error(response, 400)
    assert time.perf_counter() - start < 1


def test_custom_sample_normalises_text(client):
    response = client.post('/getCustomSample', json={'text': '  It’s  a  “test” —  ok… ', 'language': 'en'})
    assert response.status_code == 200
    assert response.get_json()['real_transcript'] == ['It\'s a "test" ok...']


# ------------------------------------------------------------------ audio limits

def test_scoring_rejects_invalid_base64(client, fake_asr):
    response = client.post('/GetAccuracyFromRecordedAudio',
                           json={'title': 'Hello world', 'base64Audio': 'data:audio/webm;base64,@@@', 'language': 'en'})
    assert_json_error(response, 400, 'bad_audio')


def test_scoring_requires_audio(client, fake_asr):
    response = client.post('/GetAccuracyFromRecordedAudio', json={'title': 'Hello world', 'language': 'en'})
    assert_json_error(response, 400, 'no_audio')


@requires_ffmpeg
@pytest.mark.parametrize('payload', [
    b'definitely not audio',
    b'#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n',
    b'ffconcat version 1.0\nfile /etc/passwd\n',
])
def test_scoring_rejects_non_audio_uploads(client, fake_asr, payload):
    assert_json_error(score(client, 'Hello world', payload), 400, 'bad_audio')


@requires_ffmpeg
def test_scoring_rejects_long_recordings_quickly(client, fake_asr):
    long_take = make_audio('ogg', seconds=40)
    start = time.perf_counter()
    assert_json_error(score(client, 'Hello world', long_take, 'audio/ogg'), 413, 'audio_too_long')
    assert time.perf_counter() - start < 10


@requires_ffmpeg
def test_scoring_rejects_formats_browsers_do_not_record(client, fake_asr):
    # A tiny FLAC can declare minutes of audio; only browser formats are accepted.
    flac = make_audio('flac', seconds=60, silent=True)
    assert_json_error(score(client, 'Hello world', flac, 'audio/flac'), 400, 'bad_audio')


def odd_rate_wav(rate=16001, seconds=1.0) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    pcm = (np.sin(2 * np.pi * 440 * t) * 0.5 * 32767).astype('<i2').tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


@requires_ffmpeg
def test_odd_sample_rate_is_scored_normally(client, fake_asr):
    # torchaudio's resampler used to build a kernel of several GB for 16001 Hz.
    # (The decode time itself is checked in test_audio_decode.py.)
    fake_asr.transcript = 'Hello world'
    response = score(client, 'Hello world', odd_rate_wav(), 'audio/wav')
    assert response.status_code == 200


# ------------------------------------------------------------------ scoring with a fake ASR

@requires_ffmpeg
@pytest.mark.parametrize('fmt,mime', [('webm', 'audio/webm'), ('ogg', 'audio/ogg'),
                                      ('mp4', 'audio/mp4'), ('wav', 'audio/wav')])
def test_scoring_happy_path(client, fake_asr, fmt, mime):
    fake_asr.transcript = 'Hello world'
    response = score(client, 'Hello world', make_audio(fmt, seconds=1.0), mime)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.mimetype == 'application/json'
    body = response.get_json()
    assert body['pronunciation_accuracy'] == '100'
    assert body['real_transcripts'] == 'Hello world'


@requires_ffmpeg
def test_scoring_response_is_json_even_with_markup_in_title(client, fake_asr):
    title = '<img src=x onerror=alert(1)> hello'
    fake_asr.transcript = 'image source hello'
    response = score(client, title, make_audio('webm'))
    assert response.status_code == 200
    assert response.mimetype == 'application/json'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


@requires_ffmpeg
def test_silent_recording_is_no_speech(client, fake_asr):
    assert_json_error(score(client, 'Hello world', make_audio('webm', silent=True)), 422, 'no_speech')
