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
"""
from string import punctuation

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
