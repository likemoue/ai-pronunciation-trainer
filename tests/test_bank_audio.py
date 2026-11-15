"""The reference voice for bank sentences: GET /tts/<language>/<key>.mp3, a
fixed URL per sentence and voice that browsers and Cloudflare may keep."""
import re

import pytest

import lambdaGetSample
import piperTTS
from conftest import requires_ffmpeg

IMMUTABLE = 'public, max-age=31536000, immutable'


def sample(client, category=1):
    response = client.post('/getSample', json={'category': category, 'language': 'en'})
    assert response.status_code == 200
    return response.get_json()


def test_a_sample_names_the_recording_of_its_sentence(client):
    data = sample(client)
    match = re.fullmatch(r'/tts/en/([0-9a-f]{16})\.mp3', data['tts_url'])
    assert match
    assert lambdaGetSample.sentence_for_audio_key('en', match.group(1)) == data['real_transcript'][0]


def test_the_key_depends_on_the_sentence_the_voice_and_the_bitrate_only(monkeypatch):
    recording = lambdaGetSample.recording_id('en')
    assert piperTTS.VOICE_CONFIGS['en'] in recording and piperTTS.MP3_BITRATE in recording
    key = lambdaGetSample.audio_key('I have a cat.', recording)
    assert key == lambdaGetSample.audio_key('I have a cat.', lambdaGetSample.recording_id('en'))
    assert key != lambdaGetSample.audio_key('I have a dog.', recording)
    monkeypatch.setattr(piperTTS, 'MP3_BITRATE', '64k')
    assert key != lambdaGetSample.audio_key('I have a cat.', lambdaGetSample.recording_id('en'))
    monkeypatch.setitem(piperTTS.VOICE_CONFIGS, 'en', 'en_US-ljspeech-high')
    assert key != lambdaGetSample.audio_key('I have a cat.', lambdaGetSample.recording_id('en'))


def test_every_bank_sentence_has_its_own_key(client):
    sample(client)  # loads the bank
    bank = lambdaGetSample._database_cache['en']
    assert len(set(bank.keys)) == len(bank.sentences)
    assert bank.recording == lambdaGetSample.recording_id('en')


@requires_ffmpeg
def test_the_recording_is_an_mp3_cached_for_good(client, fake_voice):
    data = sample(client)
    response = client.get(data['tts_url'])
    assert response.status_code == 200
    assert response.mimetype == 'audio/mpeg'
    assert response.headers['Cache-Control'] == IMMUTABLE
    assert response.data[:3] == b'ID3' or response.data[0] == 0xFF  # an MP3 frame or tag
    assert fake_voice.synthesized == [data['real_transcript'][0]]
    # The second request comes from the server's own cache.
    assert client.get(data['tts_url']).data == response.data
    assert len(fake_voice.synthesized) == 1


@requires_ffmpeg
def test_mp3_is_far_smaller_than_the_wav():
    import io
    import wave
    import numpy as np
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        t = np.arange(22050 * 3) / 22050
        w.writeframes((np.sin(2 * np.pi * 220 * t) * 8000).astype('<i2').tobytes())
    mp3 = piperTTS.encode_mp3(buffer.getvalue())
    assert len(mp3) < len(buffer.getvalue()) / 5


@pytest.mark.parametrize('path', ['/tts/en/0123456789abcdef.mp3', '/tts/en/XYZ.mp3', '/tts/en/../../webApp.py',
                                  '/tts/de/0123456789abcdef.mp3', '/tts/xx/0123456789abcdef.mp3'])
def test_anything_but_a_bank_sentence_is_not_found(client, fake_voice, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers['Cache-Control'] == 'no-store'
    assert fake_voice.synthesized == []


def test_a_busy_voice_answers_503(client, fake_voice, monkeypatch):
    data = sample(client)
    monkeypatch.setattr(piperTTS, '_synth_pending', piperTTS._SYNTH_QUEUE_LIMIT)
    response = client.get(data['tts_url'])
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '2'
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.get_json()['code'] == 'tts_busy'


def test_a_failed_encoding_answers_503(client, fake_voice, monkeypatch):
    data = sample(client)

    def broken(wav):
        raise RuntimeError('no encoder')
    monkeypatch.setattr(piperTTS, 'encode_mp3', broken)
    response = client.get(data['tts_url'])
    assert response.status_code == 503
    assert response.get_json()['code'] == 'tts_failed'
    assert response.headers['Cache-Control'] == 'no-store'
