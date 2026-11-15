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


def wrapper_with(segments, max_new_tokens=160, vad_threshold=0.0):
    model = whisper_wrapper.WhisperASRModel.__new__(whisper_wrapper.WhisperASRModel)
    model.model = FakeWhisperModel(segments)
    model.language = 'en'
    model.max_new_tokens = max_new_tokens
    model.sample_rate = 16000
    model.vad_threshold = vad_threshold
    model.vad_min_windows = 3
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


@pytest.fixture(scope='module')
def spoken_sentence():
    """A Piper reading from the evaluation set, decoded as an upload."""
    import os
    import audioPreprocessing
    from conftest import ROOT, ffmpeg_binary
    if not ffmpeg_binary():
        pytest.skip('ffmpeg is not installed')
    with open(os.path.join(ROOT, 'evaluation', 'clips', 'learner-01-clean.webm'), 'rb') as f:
        return audioPreprocessing.decode_audio(f.read(), 16000)


@pytest.mark.parametrize('kind', ['silence', 'white noise', 'hum'])
def test_no_speech_is_not_sent_to_whisper(kind):
    pytest.importorskip('faster_whisper')
    import pronunciationTrainer
    t = np.arange(16000 * 3) / 16000
    audio = {'silence': np.zeros(t.size), 'white noise': np.random.default_rng(1).uniform(-0.1, 0.1, t.size),
             'hum': 0.05 * np.sin(2 * np.pi * 50 * t)}[kind].reshape(1, -1)
    # As the trainer sends it: scaled by preprocessAudio.
    audio = pronunciationTrainer.PronunciationTrainer(None, None).preprocessAudio(audio)
    model = wrapper_with([SimpleNamespace(text=' Thank you.', words=[word(' Thank', 0.0, 0.3), word(' you.', 0.3, 0.6)])],
                         vad_threshold=0.5)
    model.processAudio(audio)
    assert model.model.calls == []
    assert model.getTranscript() == '' and model.getWordLocations() == []


def test_speech_is_sent_to_whisper_whole(spoken_sentence):
    pytest.importorskip('faster_whisper')
    import pronunciationTrainer
    audio = pronunciationTrainer.PronunciationTrainer(None, None).preprocessAudio(spoken_sentence)
    model = wrapper_with([SimpleNamespace(text=' Who', words=[word(' Who', 0.4, 0.6)])], vad_threshold=0.5)
    model.processAudio(audio)
    samples, _ = model.model.calls[0]
    assert samples.size == audio.size  # not cut to the speech
    assert model.getTranscript() == 'Who'


def test_the_gate_can_be_turned_off():
    model = wrapper_with([], vad_threshold=0)
    model.processAudio(np.zeros((1, 16000), dtype=np.float32))
    assert len(model.model.calls) == 1


def test_a_tap_far_louder_than_a_soft_voice_does_not_set_its_level():
    # A soft "Yes." 3 s into a 6 s recording, after a tap on Record 50 dB
    # louder. Scaled by its peak, the voice stayed at 0.003 of full scale.
    import pronunciationTrainer
    rate = 16000
    audio = np.zeros(rate * 6)
    audio[rate * 3:rate * 4] = 0.002 * np.sin(2 * np.pi * 220 * np.arange(rate) / rate)
    tap = np.random.default_rng(0).standard_normal(480) * np.exp(-np.arange(480) / 64)
    audio[2400:2880] += 0.7 * tap / np.abs(tap).max()
    out = pronunciationTrainer.PronunciationTrainer(None, None).preprocessAudio(audio.reshape(1, -1))
    assert out.dtype == np.float32 and out.shape == (1, rate * 6)
    assert np.abs(out[0, rate * 3:rate * 4]).max() > 0.5
    assert np.abs(out).max() <= 1.0


def test_a_recording_without_a_tap_keeps_its_shape():
    import pronunciationTrainer
    t = np.arange(16000) / 16000
    audio = (0.3 * np.sin(2 * np.pi * 220 * t) + 0.05).reshape(1, -1)
    out = pronunciationTrainer.PronunciationTrainer(None, None).preprocessAudio(audio)
    assert abs(float(out.mean())) < 1e-3  # the offset is removed
    assert 0.6 < np.abs(out).max() <= 1.0
    assert np.corrcoef(out[0], audio[0])[0, 1] > 0.99


@pytest.mark.parametrize('value,expected', [(None, 0.5), ('', 0.5), ('0.3', 0.3), ('0', 0.0), ('abc', 0.5),
                                            ('1', 0.5), ('1.5', 0.5), ('-0.1', 0.5), ('nan', 0.5)])
def test_the_vad_threshold_is_read_safely(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv('VAD_THRESHOLD', raising=False)
    else:
        monkeypatch.setenv('VAD_THRESHOLD', value)
    assert whisper_wrapper._float_env('VAD_THRESHOLD', 0.5, 0.0, 1.0) == expected


def test_a_lone_window_of_speech_does_not_open_the_gate(monkeypatch):
    pytest.importorskip('faster_whisper')
    import faster_whisper.vad
    probabilities = {'one': [0.1, 0.9, 0.1, 0.9, 0.9, 0.2], 'three': [0.1, 0.9, 0.9, 0.9, 0.2, 0.1]}
    for name, expected in (('one', False), ('three', True)):
        monkeypatch.setattr(faster_whisper.vad, 'get_vad_model',
                            lambda name=name: (lambda audio: np.array(probabilities[name]).reshape(-1, 1)))
        model = wrapper_with([], vad_threshold=0.5)
        assert model.has_speech(np.zeros(512 * 6, dtype=np.float32)) is expected, name
