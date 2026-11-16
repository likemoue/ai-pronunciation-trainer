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


def _opus(wav):
    """The upload the page sends: WebM/Opus at 32 kbps (recorder.js)."""
    import audioPreprocessing
    return subprocess.run([audioPreprocessing.ffmpeg_binary(), '-nostdin', '-loglevel', 'error', '-f', 'wav',
                           '-i', 'pipe:0', '-ac', '1', '-ar', '48000', '-c:a', 'libopus', '-b:a', '32k',
                           '-frame_duration', '60', '-f', 'webm', 'pipe:1'],
                          input=wav, capture_output=True, check=True, timeout=60).stdout


def _piper_speech(text, before=0.5, after=3.0):
    """Piper reading text, with silence before and after: (samples, rate)."""
    import base64
    import io
    import wave
    import numpy as np
    import piperTTS
    with wave.open(io.BytesIO(base64.b64decode(piperTTS.generate_wav_base64(text))), 'rb') as w:
        rate = w.getframerate()
        speech = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32) / 32768
    return np.concatenate([np.zeros(int(rate * before), np.float32), speech,
                           np.zeros(int(rate * after), np.float32)]), rate


@pytest.mark.parametrize('upload', ['wav', 'webm'])
@pytest.mark.parametrize('kind,seed', [('white noise', 1), ('white noise', 2), ('white noise', 3),
                                       ('white noise', 4), ('hum', 0)])
def test_noise_alone_is_no_speech_not_an_invented_sentence(kind, seed, upload):
    # The transformers pipeline turned noise into a sentence and scored it.
    # faster-whisper keeps by default a window it rates as probably not speech
    # when it is sure enough of the words, which noise sent as the page sends
    # it often was: "I'm going to get a little bit of a" (seeds 1-3 in WebM).
    import numpy as np
    import lambdaSpeechToScore
    t = np.arange(16000 * 3) / 16000
    samples = (np.random.default_rng(seed).standard_normal(t.size) * 0.05 if kind == 'white noise'
               else 0.05 * np.sin(2 * np.pi * 50 * t))
    audio = _wav(samples) if upload == 'wav' else _opus(_wav(samples))
    with pytest.raises(lambdaSpeechToScore.NoSpeechError):
        lambdaSpeechToScore.score('I have a cat and a dog at home.', audio, 'en')


def _frozen_speech(clip, after):
    """A reading of the evaluation set (Piper never says a text the same way
    twice, and a fresh synthesis was once heard as \"Turn on the light and turn
    on the light.\"), with `after` more seconds of silence: (samples, rate)."""
    import numpy as np
    import audioPreprocessing
    with open(os.path.join(ROOT, 'evaluation', 'clips', clip + '.webm'), 'rb') as f:
        samples = audioPreprocessing.decode_audio(f.read(), 16000)[0]
    return np.concatenate([samples, np.zeros(int(16000 * after), np.float32)]), 16000


def test_a_spoken_sentence_has_no_word_added_after_it():
    # Without Whisper's timestamps, faster-whisper added "you" after the
    # sentence in half a second of trailing silence.
    import lambdaSpeechToScore
    sentence = 'Tom ran out of gas.'
    samples, rate = _frozen_speech('bank-s05-clean', after=0.4)  # 0.6 s of silence ends the clip already
    result = lambdaSpeechToScore.score(sentence, _wav(samples, rate), 'en')
    assert len(result['real_transcript'].split()) == len(sentence.split()), result['real_transcript']


@pytest.mark.parametrize('word,spoken', [('computer', 'computer'), ('think', 'tink'), ('library', 'libary')])
def test_a_single_word_followed_by_a_pause_is_scored(word, spoken):
    # Learners often wait before they press Stop. Whisper's
    # hallucination_silence_threshold dropped such a word as invented, above
    # all a mispronounced one, of which Whisper is unsure.
    import lambdaSpeechToScore
    samples, rate = _piper_speech(spoken)
    result = lambdaSpeechToScore.score(word, _opus(_wav(samples, rate)), 'en')
    assert result['real_transcript'].strip()
    if spoken == word:
        assert int(result['pronunciation_accuracy']) >= 60, result['real_transcript']
