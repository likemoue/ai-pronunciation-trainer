"""German pipeline (from upstream). Disabled in the English edition: run with
`pytest -m de` after installing epitran and enabling ENABLED_LANGUAGES=de."""
import json

import pytest

pytestmark = pytest.mark.de
epitran = pytest.importorskip('epitran')

import ModelInterfaces  # noqa: E402
import lambdaGetSample  # noqa: E402
import RuleBasedModels  # noqa: E402
import pronunciationTrainer  # noqa: E402


def sample_lengths_ok(category: int, threshold_min: int, threshold_max: int) -> bool:
    event = {'body': json.dumps({'category': category, 'language': 'de'})}
    for _ in range(200):
        response = json.loads(lambdaGetSample.lambda_handler(event, []))
        number_of_words = len(response['real_transcript'][0].split())
        if not threshold_min < number_of_words <= threshold_max:
            return False
    return True


@pytest.mark.parametrize('category,low,high', [(1, 0, 8), (2, 8, 20), (3, 20, 10000)])
def test_german_sentence_categories(category, low, high):
    assert sample_lengths_ok(category, low, high)


def check_phonem_converter(converter: ModelInterfaces.ITextToPhonemModel, text: str, expected: str) -> bool:
    return converter.convertToPhonem(text) == expected


def test_german_phonemes():
    converter = RuleBasedModels.EpitranPhonemConverter(epitran.Epitran('deu-Latn'))
    assert check_phonem_converter(converter, 'Hallo, das ist ein Test', 'haloː, dɑːs ɪst ain tɛst')


@pytest.mark.slow
class TestGermanScore:

    def setup_method(self):
        self.trainer = pronunciationTrainer.getTrainer('de')

    def test_exact_transcription(self):
        words_real = 'Ich habe sehr viel glück, am leben und gesund zu sein'
        pairs, _, _ = self.trainer.matchSampleAndRecordedWords(words_real, words_real)
        accuracy, _ = self.trainer.getPronunciationAccuracy(pairs)
        assert int(accuracy) == 100
