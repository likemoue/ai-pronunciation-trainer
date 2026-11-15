"""The Whisper wrapper's own logic, with a stand-in for faster-whisper's model."""
from types import SimpleNamespace

import numpy as np
import pytest

whisper_wrapper = pytest.importorskip('whisper_wrapper')


class FakeWhisperModel:
    """Returns the segments it was given, and remembers how it was called."""

    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return iter(self.segments), SimpleNamespace(language='en')


def word(text, start, end):
    return SimpleNamespace(word=text, start=start, end=end, probability=0.9)


def wrapper_with(segments, max_new_tokens=160):
    model = whisper_wrapper.WhisperASRModel.__new__(whisper_wrapper.WhisperASRModel)
    model.model = FakeWhisperModel(segments)
    model.language = 'en'
    model.max_new_tokens = max_new_tokens
    model.sample_rate = 16000
    return model


def test_transcript_words_line_up_with_the_word_timestamps():
    model = wrapper_with([
        SimpleNamespace(text=' Is it raining?', words=[word(' Is', 0.0, 0.2), word(' it', 0.2, 0.4),
                                                       word(' raining?', 0.4, 0.9)]),
        SimpleNamespace(text=" I don't know.", words=[word(' I', 1.0, 1.1), word(" don't", 1.1, 1.4),
                                                      word(' know.', 1.4, 1.8)]),
    ])
    model.processAudio(np.zeros((1, 32000), dtype=np.float32))
    assert model.getTranscript() == "Is it raining? I don't know."
    locations = model.getWordLocations()
    assert [w['word'] for w in locations] == model.getTranscript().split()
    assert locations[2]['start_ts'] == pytest.approx(0.4 * 16000)
    assert locations[2]['end_ts'] == pytest.approx(0.9 * 16000)


def test_a_word_with_a_space_inside_becomes_two_words():
    # Never seen from Whisper, but the trainer would index past the end of the
    # word list if the transcript had more words than it.
    model = wrapper_with([SimpleNamespace(text=' New York', words=[word(' New York', 0.0, 0.8)]),
                          SimpleNamespace(text=' ', words=[word('  ', 0.8, 0.9)])])
    model.processAudio(np.zeros((1, 16000), dtype=np.float32))
    assert model.getTranscript() == 'New York'
    assert [w['word'] for w in model.getWordLocations()] == ['New', 'York']


@pytest.mark.parametrize('pieces,transcript', [
    ([' It', ' is', ' well', '-known.'], 'It is well-known.'),
    ([' at', ' five', ' o', "'clock."], "at five o'clock."),
    ([' at', ' 2', ':30', ' today.'], 'at 2:30 today.'),
    ([' Mr', '.', ' Smith'], 'Mr. Smith'),
])
def test_words_whisper_cuts_in_two_stay_one_word(pieces, transcript):
    # Whisper times "well-known" as " well" and "-known"; joining its words
    # with spaces scored a correct reading as two wrong words.
    words = [(piece, n * 0.5, n * 0.5 + 0.4) for n, piece in enumerate(pieces)]
    text, locations = whisper_wrapper.words_and_locations(words)
    assert text == transcript
    assert [loc['word'] for loc in locations] == transcript.split()
    joined = next(loc for loc in locations if loc['word'] == transcript.split()[-1 if len(pieces) == 3 else 2])
    assert joined['end_ts'] > joined['start_ts']


def test_a_joined_word_spans_all_its_pieces():
    text, locations = whisper_wrapper.words_and_locations([(' well', 1.0, 1.3), ('-known', 1.3, 1.9)])
    assert text == 'well-known'
    assert locations == [{'word': 'well-known', 'start_ts': 16000.0, 'end_ts': 1.9 * 16000, 'tag': 'processed'}]


def test_no_speech_gives_an_empty_transcript():
    model = wrapper_with([])
    model.processAudio(np.zeros((1, 16000), dtype=np.float32))
    assert model.getTranscript() == ''
    assert model.getWordLocations() == []


def test_decoding_is_greedy_english_with_word_timestamps():
    model = wrapper_with([], max_new_tokens=99)
    audio = np.arange(10, dtype=np.float32).reshape(1, -1)
    model.processAudio(audio)
    samples, kwargs = model.model.calls[0]
    assert samples.ndim == 1 and samples.dtype == np.float32 and samples.tolist() == list(range(10))
    assert kwargs['language'] == 'en' and kwargs['task'] == 'transcribe'
    assert kwargs['beam_size'] == 1 and kwargs['temperature'] == 0.0
    assert kwargs['word_timestamps'] is True and kwargs['without_timestamps'] is False
    # It dropped a single real word followed by a pause.
    assert 'hallucination_silence_threshold' not in kwargs
    assert kwargs['condition_on_previous_text'] is False
    assert kwargs['max_new_tokens'] == 99
    assert 'vad_filter' not in kwargs or kwargs['vad_filter'] is False
