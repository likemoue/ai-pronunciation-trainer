import base64
import io
import wave

import pytest

import piperTTS


def test_split_keeps_words_whole_and_pieces_short():
    text = ('This is a fairly long sentence without much punctuation that keeps going on and on '
            'until it is clearly longer than the limit, and then it continues a little more. Short one!')
    pieces = piperTTS.split_for_synthesis(text, max_chars=60)
    assert all(len(piece) <= 60 for piece in pieces)
    assert ' '.join(pieces).split() == text.split()


@pytest.mark.parametrize('text', [
    'Which would you like: coffee or tea?',
    'Mr. and Mrs. Smith are here.',
    "I'm tired; let's go home...",
    "Where's Tom? He's over there.",
])
def test_short_text_is_synthesised_in_one_piece(text):
    # Splitting at every ; : or abbreviation changed the reference audio.
    assert piperTTS.split_for_synthesis(text) == [text]


def test_long_text_packs_whole_sentences_into_pieces():
    sentences = ['Tom is here.', 'Mary is not.', 'They will meet at noon.', 'Then they go home.'] * 4
    text = ' '.join(sentences)
    pieces = piperTTS.split_for_synthesis(text, max_chars=60)
    assert all(len(piece) <= 60 for piece in pieces)
    assert ' '.join(pieces) == text
    # Pieces end at sentence boundaries when the sentences fit.
    assert all(piece.endswith('.') for piece in pieces)
    assert len(pieces) < len(sentences)


def test_generated_wav_contains_every_piece(fake_voice):
    text = ('word ' * 50).strip()
    wav_bytes = base64.b64decode(piperTTS.generate_wav_base64(text))
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getnframes() == sum(len(p) for p in piperTTS.split_for_synthesis(text)) * 100


def test_cache_is_bounded_by_bytes(fake_voice, monkeypatch):
    monkeypatch.setattr(piperTTS, '_CACHE_MAX_BYTES', 200_000)
    for i in range(100):
        piperTTS.generate_wav_base64(f'sentence number {i} ' + 'x' * 100)
    assert piperTTS._cache_bytes <= 200_000
    assert piperTTS._cache_bytes == sum(len(v) for v in piperTTS._cache.values())


def test_text_that_expands_into_too_many_phonemes_is_refused_before_synthesis(fake_voice):
    # espeak reads numbers and emoji as several words each; FakeVoice models
    # that by returning several phonemes per character.
    fake_voice.phonemes_per_char = 20
    with pytest.raises(piperTTS.TextTooLongError):
        piperTTS.generate_wav_base64('a1234' * 10)
    assert fake_voice.synthesized == []
    assert piperTTS._cache_bytes == 0


def test_text_within_the_phoneme_limit_is_synthesised(fake_voice):
    text = 'x' * 299
    fake_voice.phonemes_per_char = 3  # 897 phonemes, just under the limit
    assert piperTTS.generate_wav_base64(text)
    assert ''.join(fake_voice.synthesized) == text


def test_text_without_audio_raises_value_error(fake_voice, monkeypatch):
    monkeypatch.setattr(fake_voice, 'synthesize_wav', lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='no audio'):
        piperTTS.generate_wav_base64('hello')
