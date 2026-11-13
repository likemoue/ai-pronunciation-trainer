"""End-to-end check with the real models (Whisper + Piper). Run with: pytest -m slow"""
import pytest

pytestmark = pytest.mark.slow


def test_strict_warm_up_scores_a_spoken_sentence():
    import lambdaSpeechToScore
    assert lambdaSpeechToScore.warm_up('en', strict=True) is True


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
