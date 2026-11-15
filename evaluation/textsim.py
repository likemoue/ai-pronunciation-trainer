"""What the scoring makes of known transcripts, over the sentence bank.

No audio and no Whisper: for each sentence, the transcript Whisper would
write if the learner read it exactly, or left out, added or changed one word,
is given to the trainer (as tests/conftest.py's FakeASR does), and its labels
and letter colours are compared with the truth. This isolates the word
alignment and the scoring from the recogniser:

    exact       the sentence itself: every word should be Correct, no letter red
    plain       the same in lower case without punctuation (Whisper punctuates
                differently): every word Correct
    drop        an inner word left out: that word Needs work, its neighbours Correct
    add         a filler ("um") after an inner word: every word Correct
    repeat      an inner word said twice: every word Correct
    substitute  an inner word replaced by another bank word: that word flagged,
                its neighbours Correct

The plan's measurements before phase 2: 13.9% of sentences got a red letter
although the transcript matched, and when one word was left out the word
next to it was marked down in 70% of cases.
"""
import hashlib
import random
import re
import sys
from collections import Counter

import numpy as np

from evaluation import metrics

VARIANTS = ('exact', 'plain', 'drop', 'add', 'repeat', 'substitute')
FILLER = 'um'


class TranscriptASR:
    """Stands in for Whisper: the transcript it is given, with evenly spaced word times."""

    def __init__(self):
        self.transcript = ''
        self._locations = []

    def processAudio(self, audio):
        words = self.transcript.split()
        step = max(1, audio.shape[-1] // max(1, len(words)))
        self._locations = [{'word': w, 'start_ts': i * step, 'end_ts': (i + 1) * step, 'tag': 'processed'}
                           for i, w in enumerate(words)]

    def getTranscript(self):
        return self.transcript

    def getWordLocations(self):
        return self._locations


def bank_sentences():
    """The bank as the app serves it (lambdaGetSample.SentenceBank)."""
    import pandas as pd

    import lambdaGetSample
    frame = pd.read_csv('databases/data_en.csv', delimiter=';')
    return lambdaGetSample.SentenceBank(frame['sentence'].tolist()).sentences


def _rng(sentence):
    return random.Random(int(hashlib.sha256(sentence.encode('utf-8')).hexdigest()[:16], 16))


def plain(text):
    return ' '.join(re.sub(r"[^\w'\-]", '', word.lower()) for word in text.split()).strip()


def variants(sentence, vocabulary):
    """(variant, transcript, truth per word, index of the changed word or None)."""
    words = sentence.split()
    rng = _rng(sentence)
    out = [('exact', sentence, ['ok'] * len(words), None),
           ('plain', plain(sentence), ['ok'] * len(words), None)]
    if len(words) >= 3:
        k = rng.randrange(1, len(words) - 1)
        out.append(('drop', ' '.join(words[:k] + words[k + 1:]),
                    ['missing' if i == k else 'ok' for i in range(len(words))], k))
        out.append(('add', ' '.join(words[:k + 1] + [FILLER] + words[k + 1:]), ['ok'] * len(words), k))
        out.append(('repeat', ' '.join(words[:k + 1] + [words[k]] + words[k + 1:]), ['ok'] * len(words), k))
        target = metrics.normalise_word(words[k])
        candidates = [w for w in vocabulary if metrics.normalise_word(w)[:1] != target[:1]
                      and abs(len(w) - len(target)) <= 1]
        other = rng.choice(candidates or vocabulary)
        out.append(('substitute', ' '.join(words[:k] + [other] + words[k + 1:]),
                    ['error' if i == k else 'ok' for i in range(len(words))], k))
    return out


def silence(samples):
    """A recording of `samples` zeros, in the type the trainer takes (numpy
    since phase 2; a torch tensor before, for scoring older images)."""
    import pronunciationTrainer
    torch = getattr(pronunciationTrainer, 'torch', None)
    return torch.zeros((1, samples)) if torch is not None else np.zeros((1, samples), dtype=np.float32)


def score_transcript(trainer, sentence, audio):
    """The response the page gets for this transcript (the trainer's ASR is a TranscriptASR)."""
    import lambdaSpeechToScore
    result = trainer.processAudioForGivenText(audio, sentence)
    return lambdaSpeechToScore._build_response(result)


def run(sentences, every=1, check_every=25, progress=False):
    """Score every variant of every `every`-th sentence of the bank. Returns
    counts per variant, and over every check_every-th sentence a digest of
    every label and letter, which tests/test_evaluation.py recomputes (with
    every=check_every) to see that a committed report is the report of the
    code beside it. Replacement words come from the whole bank either way."""
    import pronunciationTrainer
    import RuleBasedModels
    if check_every % every:
        raise ValueError('check_every must be a multiple of every')
    asr = TranscriptASR()
    trainer = pronunciationTrainer.PronunciationTrainer(asr, RuleBasedModels.EngPhonemConverter())
    vocabulary = sorted({metrics.normalise_word(w) for s in sentences for w in s.split()} - {''})
    audio = silence(16000)
    totals = {v: Counter() for v in VARIANTS}
    digest = hashlib.sha256()
    examples = {v: [] for v in VARIANTS}
    for n in range(0, len(sentences), every):
        sentence = sentences[n]
        if progress and n % 1000 == 0:
            print(f'text simulation: {n} of {len(sentences)}', file=sys.stderr, flush=True)
        for variant, transcript, truth, k in variants(sentence, vocabulary):
            asr.transcript = transcript
            response = score_transcript(trainer, sentence, audio)
            labels = [metrics.label_name(c) for c in response['pair_accuracy_category'].split()]
            letters = response['is_letter_correct_all_words'].split()
            if n % check_every == 0:
                digest.update(f'{sentence}\t{variant}\t{" ".join(labels)}\t{" ".join(letters)}\n'.encode('utf-8'))
            t = totals[variant]
            t['sentences'] += 1
            wrong_here = neighbour_flagged = False
            for i, (truth_i, label) in enumerate(zip(truth, labels, strict=True)):
                t['words'] += 1
                t['agree'] += metrics.agrees(truth_i, label)
                if truth_i == 'ok':
                    t['ok_words'] += 1
                    t['false_alarms'] += metrics.flagged(label)
                    red = '0' in letters[i]
                    t['ok_red_letter'] += red
                    if k is not None and abs(i - k) == 1:
                        t['neighbours'] += 1
                        t['neighbour_false_alarms'] += metrics.flagged(label)
                        neighbour_flagged = neighbour_flagged or metrics.flagged(label)
                    wrong_here = wrong_here or metrics.flagged(label) or red
                else:
                    t['targets'] += 1
                    t['target_agree'] += metrics.agrees(truth_i, label)
                    t['target_flagged'] += metrics.flagged(label)
                    t[f'target_{label}'] += 1
                    wrong_here = wrong_here or not metrics.agrees(truth_i, label)
            t['sentences_with_neighbour_flagged'] += neighbour_flagged
            t['sentences_with_ok_red_letter'] += any('0' in letters[i] for i, x in enumerate(truth) if x == 'ok')
            t['sentences_all_right'] += not wrong_here
            if wrong_here and len(examples[variant]) < 4:
                examples[variant].append({'sentence': sentence, 'transcript': transcript,
                                          'labels': labels, 'letters': letters})
    return {'sentences': totals['exact']['sentences'], 'every': every, 'check_every': check_every,
            'totals': {v: dict(sorted(c.items())) for v, c in totals.items()},
            'check_digest': digest.hexdigest(), 'examples': examples}
