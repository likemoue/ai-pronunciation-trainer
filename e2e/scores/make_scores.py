"""Scoring answers for the browser tests of the result card (e2e/result.spec.mjs).

Each case is what POST /GetAccuracyFromRecordedAudio answers when Whisper hears
`heard` for `sentence`: the real trainer and response code, with a stand-in for
Whisper that returns `heard` (evenly timed). The tests answer the page's
scoring request with these, so the card is checked on the server's own format
without a voice saying each mistake.

    python e2e/scores/make_scores.py           # rewrite the JSON files
tests/test_build.py checks that the files are what this script makes.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import lambdaSpeechToScore  # noqa: E402
import pronunciationTrainer  # noqa: E402
import RuleBasedModels  # noqa: E402

# name: (sentence, what Whisper heard)
CASES = {
    # 79%, Well done: written Needs work, three Almost (th said as t), books Almost (ending left out).
    'typical-mistakes': ('Mary has written three books.', 'Mary has writing tree book.'),
    # 100%, Excellent: nothing to practise.
    'all-correct': ('I have a cat and a dog at home.', 'I have a cat and a dog at home.'),
    # 65%, Almost there (60-69).
    'almost-there': ('She sells fish at the market.', 'See sell fit at a marked.'),
    # 46%, Keep practising (under 60), and more than four words to practise: four chips and "+N more".
    'many-words': ('Things are not as bad as Tom thinks they are.', 'Tink are bat Tom tink day.'),
    # Fewer than 35% of the words heard at all: a different sentence.
    'different-sentence': ('Mary has written three books about the history of my town.', 'Mary books.'),
}


class HeardAs:
    """Stands in for Whisper: hears `transcript`, its words evenly spread over the recording."""

    def __init__(self, transcript):
        self.transcript = transcript
        self.locations = []

    def processAudio(self, audio):
        words = self.transcript.split()
        step = max(1, audio.shape[-1] // max(1, len(words)))
        self.locations = [{'word': word, 'start_ts': i * step, 'end_ts': (i + 1) * step, 'tag': 'processed'}
                          for i, word in enumerate(words)]

    def getTranscript(self):
        return self.transcript

    def getWordLocations(self):
        return self.locations


def answer(sentence, heard):
    trainer = pronunciationTrainer.PronunciationTrainer(HeardAs(heard), RuleBasedModels.EngPhonemConverter())
    # Three seconds of a quiet tone: the level scaling needs a signal, Whisper's stand-in ignores it.
    audio = (0.1 * np.sin(np.linspace(0, 3 * 2 * np.pi * 220, 3 * 16000))).astype(np.float32)[None, :]
    return lambdaSpeechToScore._build_response(trainer.processAudioForGivenText(audio, sentence))


def cases():
    return {name: {'sentence': sentence, 'heard': heard, 'answer': answer(sentence, heard)}
            for name, (sentence, heard) in CASES.items()}


def main():
    for name, case in cases().items():
        with open(os.path.join(HERE, f'{name}.json'), 'w', encoding='utf-8', newline='\n') as f:
            json.dump(case, f, ensure_ascii=False, indent=2)
            f.write('\n')
        print(name, case['answer']['pronunciation_accuracy'], case['answer']['pair_accuracy_category'],
              case['answer']['mistake_kinds'])


if __name__ == '__main__':
    main()
