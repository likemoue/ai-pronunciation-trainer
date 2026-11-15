"""End-to-end check with the real models (Whisper + Piper). Run with: pytest -m slow"""
import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.slow
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_strict_warm_up_scores_a_spoken_sentence():
    import lambdaSpeechToScore
    assert lambdaSpeechToScore.warm_up('en', strict=True) is True


def test_a_worker_start_logs_only_json_lines():
    # What a gunicorn worker does when it starts: load the models and score the
    # warm-up sentence. Progress bars or plain-text warnings would break
    # `docker logs ... | jq`.
    code = 'import webApp; webApp._warm_up_models()'
    env = {**os.environ, 'PRELOAD_LANGUAGES': 'en', 'WEB_CONCURRENCY': '1', 'PYTHONUTF8': '1'}
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True,
                            text=True, timeout=900)
    assert result.returncode == 0, result.stderr[-3000:]
    lines = [line for line in (result.stdout + result.stderr).replace('\r', '\n').splitlines() if line.strip()]
    not_json = []
    for line in lines:
        try:
            json.loads(line)
        except ValueError:
            not_json.append(line)
    assert not not_json, not_json[:5]
    assert any('Warm-up done for en' in line for line in lines)


@pytest.mark.parametrize('text', ['a' + '\U0001F600' * 299, 'a ' + '9999999 ' * 37])
def test_real_voice_refuses_text_that_reads_as_minutes_of_speech(text):
    import piperTTS
    with pytest.raises(piperTTS.TextTooLongError):
        piperTTS.generate_wav_base64(text)


def test_real_voice_reads_the_longest_practice_sentences():
    import pandas as pd
    import piperTTS
    sentences = pd.read_csv('databases/data_en.csv', delimiter=';')['sentence'].astype(str).tolist()
    for sentence in sorted(sentences, key=len)[-5:]:
        assert piperTTS.generate_wav_base64(sentence)


def _wav(samples, rate=16000):
    import io
    import wave
    import numpy as np
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
    return buffer.getvalue()


@pytest.mark.parametrize('kind', ['white noise', 'hum'])
def test_noise_alone_is_no_speech_not_an_invented_sentence(kind):
    # The transformers pipeline turned noise into a sentence and scored it.
    import numpy as np
    import lambdaSpeechToScore
    t = np.arange(16000 * 3) / 16000
    samples = (np.random.default_rng(1).standard_normal(t.size) * 0.05 if kind == 'white noise'
               else 0.05 * np.sin(2 * np.pi * 50 * t))
    with pytest.raises(lambdaSpeechToScore.NoSpeechError):
        lambdaSpeechToScore.score('I have a cat and a dog at home.', _wav(samples), 'en')


def test_a_spoken_sentence_has_no_word_added_after_it():
    # Without Whisper's timestamps, faster-whisper added "you" after the
    # sentence in half a second of trailing silence.
    import base64
    import numpy as np
    import io
    import wave
    import lambdaSpeechToScore
    import piperTTS
    sentence = 'Tom ran out of gas.'
    with wave.open(io.BytesIO(base64.b64decode(piperTTS.generate_wav_base64(sentence))), 'rb') as w:
        rate = w.getframerate()
        speech = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32) / 32768
    padded = np.concatenate([np.zeros(rate // 2, np.float32), speech, np.zeros(rate, np.float32)])
    result = lambdaSpeechToScore.score(sentence, _wav(padded, rate), 'en')
    assert len(result['real_transcript'].split()) == len(sentence.split()), result['real_transcript']
