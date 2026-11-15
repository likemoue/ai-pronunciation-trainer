"""Which word of the transcript goes with which word of the sentence, and which
letters of a word were heard as written.

Both are edit-distance (Needleman-Wunsch) alignments: every word of the
sentence is paired with one word of the transcript, in order, or with none
when it was not said; a word of the transcript paired with nothing (a word
said twice, a filler) is left out. Among all such pairings the one with the
smallest total cost wins: a pair costs how different its two words are (0 for
the same word, up to 1 for words with nothing in common), and a word left
unpaired on either side costs 1. A word left out therefore costs its own
place only, and the words around it stay with their own: dynamic time
warping, used before, gave a left-out word's place to a neighbour and marked
the neighbour down in two sentences of three (evaluation/report.md, text
simulation). Letters are aligned the same way within a word, so a word heard
exactly has no red letter (the warping path skipped one of a double letter,
as in "all", in one sentence of seven).

match_words, which the trainer uses, first reads both sides as their words
are said (canonical: "2:30" is "two thirty", "OK." is "okay") and counts a
word as heard when the dictionary says it alike (homophones, British and
American spellings): the ways Whisper writes a word are not the learner's
mistakes.
"""
import re
import unicodedata
from collections import defaultdict
from string import punctuation
from typing import NamedTuple

WORD_NOT_FOUND_TOKEN = '-'
# The cost of a word (or letter) on one side paired with nothing: as much as
# a pair with nothing in common, so a word said wrongly stays paired with the
# word it stands for instead of being counted as left out and added.
GAP_COST = 1.0
# Added to a pair of the same word punctuated differently. It only breaks
# ties: of two "happiness" in "...to happiness. Happiness is...", the one
# Whisper wrote "happiness." is the one it heard. (Not case: Whisper writes
# a fresh start "The sun was, the sun was..." in both cases.)
_PUNCTUATED_OTHERWISE = 1e-3
_EPSILON = 1e-9


def edit_distance(a, b) -> int:
    """Levenshtein distance between two sequences (insertions, deletions and
    substitutions all cost 1)."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        current = [i]
        for j, y in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def plain(word: str) -> str:
    """A word as it is compared: lower case, without punctuation."""
    return ''.join(ch for ch in word.lower() if ch not in punctuation)


def word_cost(real: str, heard: str) -> float:
    """How different two words are, from 0 (the same word) to 1: their edit
    distance, ignoring case and punctuation, over the longer one's length
    (and a thousandth more when they are punctuated differently)."""
    a, b = plain(real), plain(heard)
    if not a or not b:
        return 0.0 if a == b else 1.0
    punctuated_otherwise = real.lower() != heard.lower()
    return edit_distance(a, b) / max(len(a), len(b)) + (_PUNCTUATED_OTHERWISE if punctuated_otherwise else 0.0)


def align(reference, transcript, cost, gap=GAP_COST):
    """For each item of reference, the index of the item of transcript paired
    with it, or None. Pairs keep their order; the total cost (cost(r, t) per
    pair, gap per item left unpaired) is the smallest possible. Of equally
    cheap pairings, the one that pairs the later items of the transcript wins
    (a word said twice is paired with its second, corrected, saying)."""
    n, m = len(reference), len(transcript)
    pair_cost = [[cost(r, t) for t in transcript] for r in reference]
    total = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        total[i][0] = i * gap
    for j in range(1, m + 1):
        total[0][j] = j * gap
    for i in range(1, n + 1):
        row, above = total[i], total[i - 1]
        costs = pair_cost[i - 1]
        for j in range(1, m + 1):
            row[j] = min(above[j - 1] + costs[j - 1], above[j] + gap, row[j - 1] + gap)
    pairs = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        if abs(total[i][j] - (total[i - 1][j - 1] + pair_cost[i - 1][j - 1])) < _EPSILON:
            pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif abs(total[i][j] - (total[i - 1][j] + gap)) < _EPSILON:
            i -= 1
        else:
            j -= 1
    return pairs


def get_best_mapped_words(words_estimated: list, words_real: list):
    """For each word of words_real, the word of words_estimated (the
    transcript) paired with it and its index there, or WORD_NOT_FOUND_TOKEN
    and -1 when it was not said."""
    pairs = align(words_real, words_estimated, word_cost)
    mapped = [words_estimated[j] if j is not None else WORD_NOT_FOUND_TOKEN for j in pairs]
    indices = [j if j is not None else -1 for j in pairs]
    return mapped, indices


def letters_correct(real_word: str, heard_word: str) -> list:
    """1 for each character of real_word heard as written (paired with the
    same letter of heard_word, in any case) or that is punctuation, else 0. A
    word not heard at all (WORD_NOT_FOUND_TOKEN) has every letter 0."""
    real = real_word.lower()
    heard = '' if heard_word == WORD_NOT_FOUND_TOKEN else heard_word.lower()
    pairs = align(real, heard, lambda a, b: 0.0 if a == b else 1.0)
    return [1 if letter in punctuation or (j is not None and heard[j] == letter) else 0
            for letter, j in zip(real, pairs, strict=True)]


# ---------------------------------------------------------------- words as they are said
# Before they are aligned, the words of the sentence and of the transcript are
# both turned into the words they are said as, in lower case without
# punctuation: Whisper writes "3", "2:30" or "okay" for what the sentence spells
# "three", "two thirty" or "OK", and the learner said them right.
_ONES = ('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
         'seventeen eighteen nineteen').split()
_TENS = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()
_SCALES = ((10 ** 9, 'billion'), (10 ** 6, 'million'), (1000, 'thousand'))
_ORDINALS = {'one': 'first', 'two': 'second', 'three': 'third', 'five': 'fifth', 'eight': 'eighth', 'nine': 'ninth',
             'twelve': 'twelfth'}
_CURRENCIES = {'$': ('dollar', 'dollars'), '€': ('euro', 'euros'), '£': ('pound', 'pounds')}
_SYMBOLS = {'&': 'and', '+': 'plus', '=': 'equals', '@': 'at'}
# Abbreviations read as words, and British spellings whose American spelling
# the CMU dictionary says otherwise. (The dictionary itself equates most
# others, and homophones: RuleBasedModels.EngPhonemConverter.same_sound.)
_SPELLINGS = {
    'ok': 'okay', 'mr': 'mister', 'mrs': 'missus', 'ms': 'miz', 'dr': 'doctor', 'vs': 'versus', 'etc': 'etcetera',
    'theatre': 'theater', 'centre': 'center', 'metre': 'meter', 'metres': 'meters', 'litre': 'liter',
    'litres': 'liters', 'kilometre': 'kilometer', 'kilometres': 'kilometers', 'centimetre': 'centimeter',
    'centimetres': 'centimeters', 'organisation': 'organization', 'organisations': 'organizations',
    'organise': 'organize', 'organised': 'organized', 'organises': 'organizes', 'analyse': 'analyze',
    'analysed': 'analyzed', 'analysing': 'analyzing', 'programme': 'program', 'programmes': 'programs',
    'catalogue': 'catalog', 'dialogue': 'dialog', 'travelling': 'traveling', 'traveller': 'traveler',
    'travellers': 'travelers', 'cancelled': 'canceled', 'jewellery': 'jewelry', 'defence': 'defense',
    'licence': 'license', 'offence': 'offense', 'practise': 'practice', 'sceptical': 'skeptical',
    'pyjamas': 'pajamas', 'moustache': 'mustache', 'plough': 'plow', 'aluminium': 'aluminum',
}
# Stripped from both ends of a word before it is read (inner ones count: 2:30, 3.5).
_EDGE = '\'"“”‘’«»()[]{}.,!?;:…'


def number_words(n: int) -> list:
    """An integer in words, the American way: 105 -> one hundred five."""
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        return [_ONES[n // 100], 'hundred'] + (number_words(n % 100) if n % 100 else [])
    for scale, name in _SCALES:
        if n >= scale:
            return number_words(n // scale) + [name] + (number_words(n % scale) if n % scale else [])
    raise AssertionError(n)


def _ordinal(words: list) -> list:
    last = words[-1]
    if last in _ORDINALS:
        last = _ORDINALS[last]
    elif last.endswith('y'):
        last = last[:-1] + 'ieth'
    else:
        last += 'th'
    return words[:-1] + [last]


def _number(text: str) -> list:
    """Digits as they are read: 1,000 -> one thousand; 3.5 -> three point
    five; 1990 -> nineteen ninety; a long string of digits one by one."""
    whole, _, fraction = text.replace(',', '').partition('.')
    if len(whole) > 12:
        words = [_ONES[int(d)] for d in whole]
    elif len(whole) == 4 and 1100 <= int(whole) <= 1999:
        century, year = divmod(int(whole), 100)
        words = number_words(century) + (['hundred'] if year == 0 else
                                          ['oh', _ONES[year]] if year < 10 else number_words(year))
    else:
        words = number_words(int(whole))
    if fraction:
        words += ['point'] + [_ONES[int(d)] for d in fraction]
    return words


def _said_as(part: str) -> list:
    """The words one piece of a written word (no hyphen in it) is said as."""
    match = re.fullmatch(r'([$€£])(\d[\d,]*(?:\.\d+)?)', part)
    if match:
        singular = match.group(2) in ('1', '1.0', '1.00')
        return _number(match.group(2)) + [_CURRENCIES[match.group(1)][0 if singular else 1]]
    match = re.fullmatch(r'(\d[\d,]*(?:\.\d+)?)%', part)
    if match:
        return _number(match.group(1)) + ['percent']
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', part)
    if match:
        minutes = match.group(2)
        said = [] if minutes == '00' else ['oh', _ONES[int(minutes[1])]] if minutes[0] == '0' \
            else number_words(int(minutes))
        return number_words(int(match.group(1))) + said
    match = re.fullmatch(r'(\d+)(st|nd|rd|th)', part)
    if match:
        return _ordinal(number_words(int(match.group(1))))
    if re.fullmatch(r'\d[\d,]*(?:\.\d+)?', part):
        return _number(part)
    if part in _SYMBOLS:
        return [_SYMBOLS[part]]
    letters = ''.join(ch for ch in part if unicodedata.category(ch)[0] in 'LN')
    return [_SPELLINGS.get(letters, letters)] if letters else []


def canonical(word: str) -> list:
    """The words a written word is said as, in lower case without punctuation:
    "2:30" -> [two, thirty], "next-door" -> [next, door], "70%" -> [seventy,
    percent], "€2" -> [two, euros], "Mr." -> [mister], "1st" -> [first].
    Invisible characters (zero-width spaces, in a few bank sentences) are
    dropped. A word of punctuation alone is said as nothing."""
    text = unicodedata.normalize('NFKC', word)
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Cf').lower()
    words = []
    for part in re.split(r'[-‐‑–—/]+', text):
        words += _said_as(part.strip(_EDGE))
    return words


class WordMatch(NamedTuple):
    """How one word of the sentence was heard."""
    heard: str             # for the page: the word itself when heard as written, else what was heard in its
    #                        place (several words joined by '-'), or WORD_NOT_FOUND_TOKEN
    real_canonical: str    # the word as said ("two thirty")
    heard_canonical: str   # what was heard in its place, the same way ('' for nothing)
    first: int             # index in the transcript of the first word heard for it, -1 for none
    last: int              # and of the last


def match_words(real_words: list, heard_words: list, same_sound=None) -> list:
    """For each word of the sentence, how it was heard (WordMatch).

    Both are read as their words are said (canonical) and aligned word by
    word; a word of the sentence is heard as written when every word it is
    said as is paired with the same word, or with one the dictionary says
    alike (same_sound(a, b): homophones, spellings of one word)."""
    real = [(i, word) for i, written in enumerate(real_words) for word in canonical(written)]
    heard = [(j, word) for j, written in enumerate(heard_words) for word in canonical(written)]

    def same(a, b):
        return a == b or (same_sound is not None and same_sound(a, b))

    def cost(r, h):
        (i, a), (j, b) = r, h
        base = 0.0 if same(a, b) else edit_distance(a, b) / max(len(a), len(b))
        return base + (_PUNCTUATED_OTHERWISE if real_words[i].lower() != heard_words[j].lower() else 0.0)

    pairs = align(real, heard, cost)
    said = defaultdict(list)
    for (i, word), j in zip(real, pairs, strict=True):
        said[i].append((word, j))
    matches = []
    for i, written in enumerate(real_words):
        words = said.get(i, [])
        owners = sorted({heard[j][0] for _, j in words if j is not None})
        as_said = ' '.join(word for word, _ in words)
        if all(j is not None and same(word, heard[j][1]) for word, j in words):
            shown, heard_as = written, as_said
        else:
            shown = '-'.join(heard_words[k] for k in owners) if owners else WORD_NOT_FOUND_TOKEN
            heard_as = ' '.join(heard[j][1] for _, j in words if j is not None)
        matches.append(WordMatch(shown, as_said, heard_as, owners[0] if owners else -1, owners[-1] if owners else -1))
    return matches
