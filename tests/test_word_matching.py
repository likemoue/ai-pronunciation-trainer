"""The alignment of a transcript with its sentence (WordMatching.py)."""
import random

import numpy as np
import pytest

import WordMatching as wm


def mapped(sentence, transcript):
    words, indices = wm.get_best_mapped_words(transcript.split(), sentence.split())
    assert len(words) == len(indices) == len(sentence.split())
    return words


@pytest.mark.parametrize('a,b,distance', [('', '', 0), ('abc', '', 3), ('kitten', 'sitting', 3),
                                          ('book', 'books', 1), ('all', 'al', 1), ('flaw', 'lawn', 2)])
def test_edit_distance(a, b, distance):
    assert wm.edit_distance(a, b) == distance == wm.edit_distance(b, a)


def test_word_cost_ignores_case_and_punctuation_but_to_break_ties():
    assert wm.word_cost('home.', 'home.') == 0 == wm.word_cost('Home.', 'home.')
    assert 0 < wm.word_cost('Home.', 'home') < 0.01
    assert wm.word_cost("Don't", 'dont') == pytest.approx(0, abs=0.01)
    assert wm.word_cost('books', 'book') == pytest.approx(0.2, abs=0.01)
    assert wm.word_cost('cat', 'dog') == pytest.approx(1, abs=0.01)
    assert wm.word_cost('-', 'dog') == 1 and wm.word_cost('-', '...') == 0


def test_of_two_same_words_the_one_written_alike_is_paired():
    sentence = 'There is no path to happiness. Happiness is the path.'.split()
    words, indices = wm.get_best_mapped_words('There is no path to happiness. is the path.'.split(), sentence)
    assert indices == [0, 1, 2, 3, 4, 5, -1, 6, 7, 8]


def test_an_exact_transcript_maps_every_word_to_itself():
    sentence = 'Someone will have to tell Tom.'
    words, indices = wm.get_best_mapped_words(sentence.split(), sentence.split())
    assert words == sentence.split() and indices == list(range(6))


def test_a_word_left_out_leaves_its_neighbours_alone():
    # Dynamic time warping gave "yellow"'s place to a neighbour.
    assert mapped('Look through the yellow pages.', 'Look through the pages.') == \
        ['Look', 'through', 'the', '-', 'pages.']
    assert mapped('The dog ran after a fox.', 'The dog ran a fox.') == ['The', 'dog', 'ran', '-', 'a', 'fox.']
    assert mapped('Luckily, it was warm this week.', 'It was warm this week.') == \
        ['-', 'It', 'was', 'warm', 'this', 'week.']
    assert mapped('The glass is full of milk.', 'The glass is full of.') == ['The', 'glass', 'is', 'full', 'of.', '-']


def test_words_added_or_said_twice_are_left_out():
    assert mapped('Mary has more clothes than Tom.', 'Mary has um more clothes than Tom.') == \
        ['Mary', 'has', 'more', 'clothes', 'than', 'Tom.']
    # A word said twice is paired with its second saying.
    words, indices = wm.get_best_mapped_words('Tom looked through through the file.'.split(),
                                              'Tom looked through the file.'.split())
    assert words == ['Tom', 'looked', 'through', 'the', 'file.'] and indices == [0, 1, 3, 4, 5]
    # A fresh start: the sentence is paired with the second start.
    words, indices = wm.get_best_mapped_words('The sun was, the sun was hidden by thick clouds.'.split(),
                                              'The sun was hidden by thick clouds.'.split())
    assert words == ['the', 'sun', 'was', 'hidden', 'by', 'thick', 'clouds.'] and indices == [3, 4, 5, 6, 7, 8, 9]


def test_a_word_said_otherwise_stays_in_its_place():
    assert mapped('Who do you think will win?', 'Who do you tink will win?') == \
        ['Who', 'do', 'you', 'tink', 'will', 'win?']
    assert mapped('We have to help Tom.', 'We have to help talk.') == ['We', 'have', 'to', 'help', 'talk.']
    # Nothing in common with the word it replaced: still paired with it.
    assert mapped('I have a cat.', 'I have the cat.') == ['I', 'have', 'the', 'cat.']


def test_nothing_heard_maps_nothing():
    assert mapped('Hello there.', '') == ['-', '-']
    assert wm.get_best_mapped_words(['Hello'], []) == ([], [])


@pytest.mark.parametrize('real,heard,flags', [
    ('all', 'all', [1, 1, 1]),  # dynamic time warping skipped one of a double letter
    ('will', 'will', [1, 1, 1, 1]),
    ('Tom.', 'tom', [1, 1, 1, 1]),
    ("don't", 'dont', [1, 1, 1, 1, 1]),
    ('books', 'book', [1, 1, 1, 1, 0]),
    ('think', 'tink', [1, 0, 1, 1, 1]),
    ('cat', 'cap', [1, 1, 0]),
    ('home.', '-', [0, 0, 0, 0, 1]),
    ('home', 'phone', [1, 1, 0, 1]),
])
def test_letters_heard_as_written(real, heard, flags):
    assert wm.letters_correct(real, heard) == flags


@pytest.mark.parametrize('written,said', [
    ('2:30.', ['two', 'thirty']), ('6:00', ['six']), ('2:05', ['two', 'oh', 'five']),
    ('3-day', ['three', 'day']), ('next-door', ['next', 'door']), ('70%', ['seventy', 'percent']),
    ('€2.', ['two', 'euros']), ('$1', ['one', 'dollar']), ('1st', ['first']), ('22nd', ['twenty', 'second']),
    ('105', ['one', 'hundred', 'five']), ('1,000', ['one', 'thousand']), ('1990', ['nineteen', 'ninety']),
    ('3.5', ['three', 'point', 'five']), ('Mr.', ['mister']), ('OK.', ['okay']), ("o'clock", ['oclock']),
    ('“Hello,”', ['hello']), ('&', ['and']), ('...', []), ('​​as', ['as']), ('André', ['andré']),
    ('theatre', ['theater']),
])
def test_words_are_read_as_they_are_said(written, said):
    assert wm.canonical(written) == said


@pytest.fixture(scope='module')
def same_sound():
    import RuleBasedModels
    return RuleBasedModels.EngPhonemConverter().same_sound


def heard(sentence, transcript, same_sound):
    return [m.heard for m in wm.match_words(sentence.split(), transcript.split(), same_sound)]


@pytest.mark.parametrize('sentence,transcript', [
    ('We need to get home before 2:30.', 'We need to get home before two thirty.'),
    ('Wait just 3 minutes.', 'Wait just three minutes.'),
    ('Wait just three minutes.', 'Wait just 3 minutes.'),
    ('We were next-door neighbors.', 'We were next door neighbours.'),
    ("It's OK.", "It's okay."),
    ('A small cup of coffee costs €2.', 'A small cup of coffee costs 2 euros.'),
    ('The surface of the earth is 70% water.', 'The surface of the earth is 70 percent water.'),
    ('Mr. Smith lives in Kyoto now.', 'Mister Smith lives in Kyoto now.'),
    ('What colour are her eyes?', 'What color are her eyes?'),
    ('He loves theatre.', 'He loves theater.'),
    ('I want two apples.', 'I want to apples.'),  # homophones: the same sound
    ('Our grandfather learned five languages ​​as a child.', 'Our grandfather learned five languages as a child.'),
])
def test_another_way_of_writing_the_same_words_is_heard_as_written(sentence, transcript, same_sound):
    assert heard(sentence, transcript, same_sound) == sentence.split()


def test_a_word_said_otherwise_is_still_heard_otherwise(same_sound):
    assert heard('Who do you think will win?', 'Who do you tink will win?', same_sound)[3] == 'tink'
    assert heard('Mary has written three books.', 'Mary has written three book.', same_sound)[4] == 'book.'
    assert heard('Wait just 3 minutes.', 'Wait just tree minutes.', same_sound)[2] == 'tree'
    match = wm.match_words('We need to get home before 2:30.'.split(), 'We need to get home before 2:40.'.split())[6]
    assert (match.heard, match.real_canonical, match.heard_canonical) == ('2:40.', 'two thirty', 'two forty')
    assert wm.match_words(['Hello'], [])[0] == wm.WordMatch('-', 'hello', '', -1, -1)


def test_a_word_heard_in_two_parts_spans_them_both():
    first, second = wm.match_words(['2:30', 'today.'], ['two', 'thirty', 'today.'])
    assert (first.heard, first.first, first.last) == ('2:30', 0, 1)
    assert (second.first, second.last) == (2, 2)


def test_no_bank_sentence_read_exactly_gets_a_red_letter_or_a_moved_word():
    from evaluation import textsim
    sentences = textsim.bank_sentences()
    for sentence in random.Random(3).sample(sentences, 500):
        words = sentence.split()
        assert mapped(sentence, sentence) == words
        assert all(all(wm.letters_correct(w.lower(), w)) for w in words), sentence


def test_a_word_left_out_of_a_bank_sentence_marks_down_no_other_word():
    from evaluation import textsim
    sentences = [s for s in textsim.bank_sentences() if len(s.split()) >= 3]
    for sentence in random.Random(4).sample(sentences, 500):
        words = sentence.split()
        k = random.Random(sentence).randrange(1, len(words) - 1)
        result, indices = wm.get_best_mapped_words(words[:k] + words[k + 1:], words)
        # One word is left unpaired: the one left out, or the same word next to it ("that that").
        assert indices.count(-1) == 1, (sentence, k, result)
        gap = indices.index(-1)
        assert wm.plain(words[gap]) == wm.plain(words[k]), (sentence, k, result)
        assert all(wm.plain(result[i]) == wm.plain(words[i]) for i in range(len(words)) if i != gap), sentence


def test_the_trainer_scores_another_way_of_writing_as_correct(fake_asr):
    # Whisper writes digits and times its own way: the learner said the words right.
    import lambdaSpeechToScore
    trainer = lambdaSpeechToScore._trainer_cache['en']
    fake_asr.transcript = 'We need to get home before two thirty.'
    result = trainer.processAudioForGivenText(np.zeros((1, 32000), dtype=np.float32),
                                              'We need to get home before 2:30.')
    response = lambdaSpeechToScore._build_response(result)
    assert response['pronunciation_accuracy'] == '100'
    assert response['pair_accuracy_category'] == '0 0 0 0 0 0 0'
    assert '0' not in response['is_letter_correct_all_words']
