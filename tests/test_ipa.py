"""The in-memory CMU dictionary (RuleBasedModels.CmuIpa) gives exactly the IPA
that eng_to_ipa.convert gives, which reads the dictionary from SQLite on every
call."""
import os
import random
import sqlite3
import time

import eng_to_ipa
import eng_to_ipa.transcribe
import pandas as pd
import pytest

import RuleBasedModels
import validation

# Words the scorer meets in sentences and in Whisper's transcripts: punctuation
# around and inside words, contractions, numbers, hyphens, accents, capitals,
# the "-" that stands for a missing word, and words that are not in the
# dictionary at all.
EDGE_CASES = [
    '', ' ', '-', '--', '...', '?', "'", '"', 'a', 'A', 'I', 'the', 'The', 'THE',
    'read', 'live', 'record', 'object', 'present', "don't", "Don't", "it's", "o'clock",
    "rock'n'roll", "students'", "'quoted'", '"Hello,"', 'home.', 'Hello!', '(maybe)',
    '[note]', 'U.S.', 'e.g.', 'Mr.', 'Dr', 'co-operate', 'well-known', 'mother-in-law',
    '2', '30', '2:30', '1990s', '3rd', '100%', '$5', '#1', 'naïve', 'café', 'André',
    'résumé', 'Zoë', 'xyzzyq', 'qwrtplk', 'cat/dog', 'and/or', 'x' * 40,
    'I have a cat and a dog at home.', 'Hello, how are you today?',
    "What's the time? It's half past two.", 'She said: "Wait -- no!"',
]


@pytest.fixture(scope='module')
def cmu():
    return RuleBasedModels.cmu_ipa()


@pytest.fixture(scope='module')
def bank_sentences():
    sentences = pd.read_csv('databases/data_en.csv', delimiter=';')['sentence'].astype(str).tolist()
    return [validation.normalize_text(s) for s in sentences if validation.normalize_text(s)]


def original(text):
    return eng_to_ipa.convert(text)


@pytest.mark.parametrize('text', EDGE_CASES)
def test_edge_cases_match_eng_to_ipa(cmu, text):
    assert cmu.convert(text) == original(text)


def test_each_word_of_the_edge_cases_matches(cmu):
    words = {word for text in EDGE_CASES for word in text.split()}
    for word in sorted(words):
        assert cmu.convert(word) == original(word), word


def test_a_sample_of_the_bank_matches(cmu, bank_sentences):
    # eng_to_ipa as installed takes 10-20 ms a call, so here a fixed sample of
    # sentences and every word of it; the whole bank is compared below.
    sample = random.Random(20261115).sample(bank_sentences, 40)
    for sentence in sample:
        assert cmu.convert(sentence) == original(sentence), sentence
    for word in sorted({word for sentence in sample for word in sentence.split()}):
        assert cmu.convert(word) == original(word), word


def test_the_converter_strips_eng_to_ipa_markers():
    converter = RuleBasedModels.EngPhonemConverter()
    assert converter.convertToPhonem('xyzzyq cat') == original('xyzzyq cat').replace('*', '')
    assert '*' not in converter.convertToPhonem('xyzzyq')


def test_every_dictionary_word_is_loaded(cmu):
    # 133,779 rows hold 125,000 distinct words.
    assert len(cmu) == 125000


def test_a_lookup_is_fast(cmu):
    words = 'I have a cat and a dog at home'.split()
    start = time.perf_counter()
    for i in range(2000):
        cmu.convert(words[i % len(words)] + str(i))  # never cached
    per_call_ms = (time.perf_counter() - start) / 2000 * 1000
    assert per_call_ms < 1, f'{per_call_ms:.2f} ms per word'


@pytest.fixture
def indexed_eng_to_ipa(monkeypatch):
    """eng_to_ipa.convert as it is, reading an indexed in-memory copy of its
    own dictionary: the same SQL query on the same rows, but 0.1 ms a call
    instead of 10-20 ms, so the whole bank can be compared in a few seconds.
    (Without the index, the comparison took 6 minutes and also matched.)"""
    path = os.path.join(os.path.dirname(eng_to_ipa.transcribe.__file__), 'resources', 'CMU_dict.db')
    source = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    copy = sqlite3.connect(':memory:', check_same_thread=False)
    source.backup(copy)
    source.close()
    copy.execute('CREATE INDEX test_word ON dictionary (word)')
    monkeypatch.setattr(eng_to_ipa.transcribe, 'mode_type', lambda mode: copy.cursor())
    yield eng_to_ipa.convert
    copy.close()


def test_every_bank_sentence_and_word_matches(cmu, bank_sentences, indexed_eng_to_ipa):
    mismatches = [s for s in bank_sentences if cmu.convert(s) != indexed_eng_to_ipa(s)]
    words = sorted({word for sentence in bank_sentences for word in sentence.split()})
    mismatches += [w for w in words if cmu.convert(w) != indexed_eng_to_ipa(w)]
    # The whole bank was read (9,318 sentences since it lost its person names on 2026-11-17).
    assert len(bank_sentences) > 9000 and len(words) > 9000
    assert not mismatches, mismatches[:20]
