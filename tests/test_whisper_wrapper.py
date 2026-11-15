"""The Whisper wrapper's own logic, without loading the model."""
import numpy as np
import pytest

whisper_wrapper = pytest.importorskip('whisper_wrapper')


@pytest.mark.parametrize('raw,clean', [
    (' Is it raining ?', ' Is it raining?'),
    (' I have a cat , and a dog .', ' I have a cat, and a dog.'),
    (" It 's fine !", " It's fine!"),
    (" I don't know", " I don't know"),
    (' Hello world', ' Hello world'),
])
def test_spaces_before_punctuation_are_removed_as_transformers_4_did(raw, clean):
    assert whisper_wrapper.clean_up_spaces(raw) == clean


def test_transcript_words_line_up_with_the_word_timestamps():
    # transformers 5 leaves " ?" in the text, while the word chunks attach the
    # question mark to "raining"; the trainer indexes both lists the same way.
    model = whisper_wrapper.WhisperASRModel.__new__(whisper_wrapper.WhisperASRModel)
    model.sample_rate = 16000
    model._generate_kwargs = {}
    model.asr = lambda audio, generate_kwargs: {'text': ' Is it raining ?', 'chunks': [
        {'text': ' Is', 'timestamp': (0.0, 0.2)},
        {'text': ' it', 'timestamp': (0.2, 0.4)},
        {'text': ' raining?', 'timestamp': (0.4, 0.9)},
    ]}
    model.processAudio(np.zeros((1, 16000), dtype=np.float32))
    assert model.getTranscript() == ' Is it raining?'
    assert len(model.getTranscript().split()) == len(model.getWordLocations())
