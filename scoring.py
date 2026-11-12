from dataclasses import dataclass
from string import punctuation
import numpy as np
import WordMetrics


@dataclass
class ScoreResult:
    score: int
    category: str
    word_details: list
    letter_flags: str


class ScoringModule:

    def __init__(self, phonem_converter):
        self.phonem_converter = phonem_converter

    def calculate_score(self, transcription: str, reference: str) -> ScoreResult:
        words_real = reference.split()
        words_spoken = transcription.split()

        import WordMatching as wm
        mapped_words, _ = wm.get_best_mapped_words(words_spoken, words_real)

        word_details = []
        total_mismatches = 0.0
        total_phonemes = 0.0

        for i, real_word in enumerate(words_real):
            spoken_word = mapped_words[i] if i < len(mapped_words) else '-'

            real_ipa = self.phonem_converter.convertToPhonem(real_word)
            spoken_ipa = self.phonem_converter.convertToPhonem(spoken_word)

            real_clean = self._remove_punctuation(real_ipa).lower()
            spoken_clean = self._remove_punctuation(spoken_ipa).lower()

            mismatches = WordMetrics.edit_distance_python(real_clean, spoken_clean)
            phoneme_count = len(real_clean)

            total_mismatches += mismatches
            total_phonemes += phoneme_count

            word_accuracy = (phoneme_count - mismatches) / phoneme_count * 100 if phoneme_count > 0 else 100.0
            word_details.append({
                'real': real_word,
                'spoken': spoken_word,
                'real_ipa': real_ipa,
                'spoken_ipa': spoken_ipa,
                'accuracy': round(word_accuracy, 1),
            })

        if total_phonemes == 0:
            score = 100
        else:
            score = int(np.round((total_phonemes - total_mismatches) / total_phonemes * 100))

        category = self._categorize(score)

        letter_flags = self._compute_letter_flags(words_real, mapped_words)

        return ScoreResult(
            score=score,
            category=category,
            word_details=word_details,
            letter_flags=letter_flags,
        )

    def _categorize(self, score: int) -> str:
        if score >= 80:
            return 'Excellent'
        elif score >= 60:
            return 'Good'
        else:
            return 'Needs Work'

    def _remove_punctuation(self, word: str) -> str:
        return ''.join([char for char in word if char not in punctuation])

    def _compute_letter_flags(self, words_real, mapped_words) -> str:
        import WordMatching as wm
        flags = []
        for i, word_real in enumerate(words_real):
            spoken = mapped_words[i] if i < len(mapped_words) else '-'
            if spoken == '-':
                flags.append('0' * len(word_real))
            else:
                mapped_letters, _ = wm.get_best_mapped_words(spoken, word_real)
                is_correct = wm.getWhichLettersWereTranscribedCorrectly(
                    word_real, mapped_letters)
                flags.append(''.join(str(c) for c in is_correct))
        return ' '.join(flags)
