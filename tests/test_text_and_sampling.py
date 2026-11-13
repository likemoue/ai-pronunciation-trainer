import pandas as pd
import pytest

import lambdaGetSample
import validation


@pytest.fixture(scope='module')
def bank_sentences():
    return pd.read_csv('databases/data_en.csv', delimiter=';')['sentence'].astype(str).tolist()


def test_normalize_is_idempotent_on_the_whole_bank(bank_sentences):
    for sentence in bank_sentences:
        once = validation.normalize_text(sentence)
        assert validation.normalize_text(once) == once


def test_every_bank_sentence_passes_the_scoring_validator(bank_sentences):
    for sentence in bank_sentences:
        validation.practice_text(sentence)


def test_sentence_bank_buckets_match_categories(bank_sentences):
    bank = lambdaGetSample.SentenceBank(bank_sentences)
    assert len(bank.by_category[0]) == len(bank)
    assert sum(len(bank.by_category[c]) for c in (1, 2, 3)) == len(bank)
    for category in (1, 2, 3):
        assert bank.by_category[category], f'category {category} is empty'
        for idx in bank.by_category[category]:
            assert lambdaGetSample.getSentenceCategory(bank.sentences[idx]) == category


@pytest.mark.parametrize('value,expected', [(0, 0), (1, 1), ('2', 2), (3.0, 3), (' 3 ', 3)])
def test_category_accepts_valid_values(value, expected):
    assert validation.category(value) == expected


@pytest.mark.parametrize('value', [4, -1, '4', 'abc', None, True, False, 1.5, [], {}])
def test_category_rejects_invalid_values(value):
    with pytest.raises(validation.ValidationError):
        validation.category(value)


def test_practice_text_limits():
    assert validation.practice_text('  Hello   world  ') == 'Hello world'
    with pytest.raises(validation.ValidationError):
        validation.practice_text('x' * (validation.MAX_TEXT_CHARS + 1))
    with pytest.raises(validation.ValidationError):
        validation.practice_text('a ' * (validation.MAX_TEXT_WORDS + 1))
    with pytest.raises(validation.ValidationError):
        validation.practice_text(12345)
    assert validation.practice_text('Café au lait is a French drink') == 'Café au lait is a French drink'
