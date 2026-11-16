import random

import pandas as pd
import pytest

import lambdaGetSample
import validation

# The C1 controls that stand for Windows-1252 punctuation (… ‘ ’ “ ” – —) in text
# from a page decoded as Latin-1, and the invisible characters normalize_text drops.
WINDOWS_1252_PUNCTUATION = [0x85, 0x91, 0x92, 0x93, 0x94, 0x96, 0x97]
INVISIBLE = ['\N{ZERO WIDTH SPACE}', '\N{ZERO WIDTH NON-JOINER}', '\N{ZERO WIDTH JOINER}', '\N{WORD JOINER}',
             '\N{ZERO WIDTH NO-BREAK SPACE}', '\N{SOFT HYPHEN}']
# Pasted from such a page: a byte order mark, quotes, a dash, a soft hyphen, a zero-width space, an ellipsis.
PASTED = '\N{ZERO WIDTH NO-BREAK SPACE}It\x92s a \x93test\x94 \x96 o\N{SOFT HYPHEN}k\N{ZERO WIDTH SPACE}\x85'


def code_point(ch):
    return f'U+{ord(ch):04X}'


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


def test_word_and_character_limits_have_their_own_messages():
    with pytest.raises(validation.ValidationError, match='characters'):
        validation.practice_text('x' * (validation.MAX_TEXT_CHARS + 1))
    with pytest.raises(validation.ValidationError, match='words'):
        validation.practice_text('a ' * (validation.MAX_TEXT_WORDS + 1))


@pytest.mark.parametrize('word', ['André', '10', '2:30', 'naïve', 'São', 'İstanbul', 'Hello,'])
def test_speech_text_accepts_single_latin_words_and_numbers(word):
    assert validation.speech_text(word) == validation.normalize_text(word)


@pytest.mark.parametrize('value', ['你好', 'Привет', 'ß' * 25, 'Xin chào các bạn học sinh', '', None, 42])
def test_speech_text_rejects_everything_else_practice_text_rejects(value):
    with pytest.raises(validation.ValidationError):
        validation.speech_text(value)


def test_speech_text_still_accepts_whole_practice_sentences(bank_sentences):
    for sentence in bank_sentences[:2000]:
        validation.speech_text(sentence)


# ------------------------------------------------------------------ pasted text
@pytest.mark.parametrize('code', WINDOWS_1252_PUNCTUATION, ids=hex)
def test_windows_1252_punctuation_reads_as_the_punctuation_it_stands_for(code):
    c1, meant = chr(code), bytes([code]).decode('cp1252')  # '\x92' stands for '’'
    text = f'{c1}It{c1}s a {c1}test{c1} {c1} ok{c1}'
    assert validation.normalize_text(text) == validation.normalize_text(text.replace(c1, meant))
    assert c1 not in validation.practice_text(text)


def test_text_pasted_through_windows_1252_is_read_as_written():
    assert validation.practice_text(PASTED) == 'It\'s a "test" ok...'
    assert validation.practice_text('Well\x97yes, \x91maybe\x92\x85') == "Well yes, 'maybe'..."


@pytest.mark.parametrize('invisible', INVISIBLE, ids=code_point)
def test_invisible_characters_are_dropped(invisible):
    assert validation.practice_text(f'{invisible}Hel{invisible}lo world{invisible}') == 'Hello world'
    assert validation.normalize_text(f'Hello {invisible} world') == 'Hello world'
    assert validation.speech_text(f'Hel{invisible}lo') == 'Hello'
    assert validation.normalize_text(invisible) == ''


@pytest.mark.parametrize('control', ['\x00', '\x08', '\x0e', '\x1b', '\x7f', '\x80', '\x81', '\x82', '\x84', '\x86',
                                     '\x8b', '\x95', '\x98', '\x9b', '\x9f', chr(0xD800), chr(0xDFFF)], ids=code_point)
def test_other_controls_and_lone_surrogates_are_still_refused(control):
    # Of the C1 controls only WINDOWS_1252_PUNCTUATION stand for punctuation
    # that the text normalisation already straightens; the rest are refused as
    # before, among them the places of the low and angle quotes (0x82, 0x84,
    # 0x8B, 0x9B: ‚ „ ‹ ›, which it leaves as they are) and of the bullet (0x95).
    for check, text in ((validation.practice_text, f'I like ap{control}ples'),
                        (validation.speech_text, f'ap{control}ples')):
        with pytest.raises(validation.ValidationError) as refused:
            check(text)
        assert refused.value.code == 'text_bad_characters'


def test_normalize_stays_idempotent_with_pasted_characters():
    text = ('\N{ZERO WIDTH NO-BREAK SPACE}\x93Don\x92t\x94 \x96 co\N{SOFT HYPHEN}operate\N{ZERO WIDTH SPACE}, '
            'wait\x85 \N{WORD JOINER}ok\x97fine')
    once = validation.normalize_text(text)
    assert once == '"Don\'t" cooperate, wait... ok fine'
    assert validation.normalize_text(once) == once
    alphabet = ['a', 'b', ' ', '.', '-', "'", '\t', '\x1c', '‘', '“', '–', '…',
                *map(chr, WINDOWS_1252_PUNCTUATION), *INVISIBLE]
    rng = random.Random(7)
    for _ in range(2000):
        text = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(1, 30)))
        once = validation.normalize_text(text)
        assert validation.normalize_text(once) == once, repr(text)


def test_the_routes_accept_text_pasted_through_windows_1252(client, fake_voice):
    response = client.post('/getCustomSample', json={'text': PASTED, 'language': 'en'})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()['real_transcript'] == ['It\'s a "test" ok...']
    response = client.post('/getAudioFromText', json={'value': PASTED, 'language': 'en'})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert fake_voice.synthesized == ['It\'s a "test" ok...']


@pytest.mark.parametrize('word,said', [('don\x92t', "don't"), ('Hel\N{SOFT HYPHEN}lo', 'Hello'),
                                       ('\N{ZERO WIDTH SPACE}book\x85', 'book...')])
def test_the_voice_reads_a_pasted_word_without_its_hidden_characters(client, fake_voice, word, said):
    response = client.post('/getAudioFromText', json={'value': word, 'language': 'en'})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert fake_voice.synthesized == [said]
