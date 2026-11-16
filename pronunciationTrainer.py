
import numpy as np
import models as mo
import WordMatching as wm
import ModelInterfaces as mi
import RuleBasedModels
import language_registry
import time


def getTrainer(language: str):

    config = language_registry.get(language)
    asr_model = mo.getASRModel(language, use_whisper=config.asr_use_whisper)

    if config.phonem_type == 'epitran':
        import epitran  # only needed for German, which the English image does not install
        phonem_converter = RuleBasedModels.EpitranPhonemConverter(
            epitran.Epitran(config.phonem_args['language_code']))
    elif config.phonem_type == 'eng_to_ipa':
        phonem_converter = RuleBasedModels.EngPhonemConverter()
    else:
        raise ValueError(f'Unknown phonem type: {config.phonem_type}')

    trainer = PronunciationTrainer(asr_model, phonem_converter)
    return trainer


class PronunciationTrainer:
    current_transcript: str
    current_ipa: str

    current_recorded_audio: np.ndarray
    current_recorded_transcript: str
    current_recorded_word_locations: list
    current_recorded_intonations: np.ndarray
    current_words_pronunciation_accuracy = []
    categories_thresholds = np.array([80, 60, 59])

    sampling_rate = 16000

    def __init__(self, asr_model: mi.IASRModel, word_to_ipa_coverter: mi.ITextToPhonemModel) -> None:
        self.asr_model = asr_model
        self.ipa_converter = word_to_ipa_coverter

    def getTranscriptAndWordsLocations(self, audio_length_in_samples: int):

        audio_transcript = self.asr_model.getTranscript()
        word_locations_in_samples = self.asr_model.getWordLocations()

        fade_duration_in_samples = 0.05*self.sampling_rate
        word_locations_in_samples = [(int(np.maximum(0, word['start_ts']-fade_duration_in_samples)), int(np.minimum(
            audio_length_in_samples-1, word['end_ts']+fade_duration_in_samples))) for word in word_locations_in_samples]

        return audio_transcript, word_locations_in_samples

    def getWordsRelativeIntonation(self, Audio: np.ndarray, word_locations: list):
        intonations = np.zeros((len(word_locations), 1))
        intonation_fade_samples = 0.3*self.sampling_rate
        for word in range(len(word_locations)):
            intonation_start = int(np.maximum(
                0, word_locations[word][0]-intonation_fade_samples))
            intonation_end = int(np.minimum(
                Audio.shape[1]-1, word_locations[word][1]+intonation_fade_samples))
            intonations[word] = np.sqrt(np.mean(
                Audio[0][intonation_start:intonation_end]**2))

        intonations = intonations/np.mean(intonations)
        return intonations

    ##################### ASR Functions ###########################

    def processAudioForGivenText(self, recordedAudio: np.ndarray = None, real_text=None):

        start = time.perf_counter()
        recording_transcript, recording_ipa, word_locations = self.getAudioTranscript(
            recordedAudio)
        asr_ms = (time.perf_counter() - start) * 1000
        if not any(ch.isalnum() for ch in recording_transcript):
            # Nothing was recognised: there are no words to align or score.
            return {'recording_transcript': '', 'timings_ms': {'asr': round(asr_ms)}}

        start = time.perf_counter()
        real_and_transcribed_words, real_and_transcribed_words_ipa, matches = self.matchSampleAndRecordedWords(
            real_text, recording_transcript)
        match_ms = (time.perf_counter() - start) * 1000

        start_time, end_time = self.getWordLocationsFromRecordInSeconds(
            word_locations, matches)

        pronunciation_accuracy, current_words_pronunciation_accuracy = self.getPronunciationAccuracy(
            matches)

        # The typical mistake each word was heard with ('ending', 'th', 'sh'),
        # or '' for none: it caps the word at Almost, and the page says what
        # to fix.
        mistake_kinds = [wm.known_mistake(match.real_canonical, match.heard_canonical) for match in matches]

        pronunciation_categories = self.getWordsPronunciationCategory(
            current_words_pronunciation_accuracy, mistake_kinds)

        result = {'recording_transcript': recording_transcript,
                  'real_and_transcribed_words': real_and_transcribed_words,
                  'recording_ipa': recording_ipa, 'start_time': start_time, 'end_time': end_time,
                  'real_and_transcribed_words_ipa': real_and_transcribed_words_ipa, 'pronunciation_accuracy': pronunciation_accuracy,
                  'pronunciation_categories': pronunciation_categories,
                  'mistake_kinds': mistake_kinds,
                  'timings_ms': {'asr': round(asr_ms), 'match': round(match_ms)}}

        return result

    def getAudioTranscript(self, recordedAudio: np.ndarray = None):
        current_recorded_audio = recordedAudio

        current_recorded_audio = self.preprocessAudio(
            current_recorded_audio)

        self.asr_model.processAudio(current_recorded_audio)

        current_recorded_transcript, current_recorded_word_locations = self.getTranscriptAndWordsLocations(
            current_recorded_audio.shape[1])
        current_recorded_ipa = self.ipa_converter.convertToPhonem(
            current_recorded_transcript)

        return current_recorded_transcript, current_recorded_ipa, current_recorded_word_locations

    def getWordLocationsFromRecordInSeconds(self, word_locations, matches) -> list:
        """Where each word of the sentence was said: from the start of the first
        word of the transcript heard for it to the end of the last. (A word
        not heard gets the transcript's last word; the page plays nothing for it.)"""
        start_time = []
        end_time = []
        for match in matches:
            start_time.append(float(word_locations[match.first][0])/self.sampling_rate)
            end_time.append(float(word_locations[match.last][1])/self.sampling_rate)
        return ' '.join([str(time) for time in start_time]), ' '.join([str(time) for time in end_time])

    ##################### END ASR Functions ###########################

    ##################### Evaluation Functions ###########################
    def matchSampleAndRecordedWords(self, real_text, recorded_transcript):
        """(sentence word, what was heard for it) pairs, the same as IPA, and
        how each word was heard (WordMatching.WordMatch). Spellings and
        homophones count as the word when the IPA converter can tell them
        (same_sound, English)."""
        words_estimated = recorded_transcript.split()

        if real_text is None:
            words_real = self.current_transcript[0].split()
        else:
            words_real = real_text.split()

        matches = wm.match_words(words_real, words_estimated, getattr(self.ipa_converter, 'same_sound', None))

        real_and_transcribed_words = []
        real_and_transcribed_words_ipa = []
        for word, match in zip(words_real, matches, strict=True):
            real_and_transcribed_words.append((word, match.heard))
            real_and_transcribed_words_ipa.append((self.ipa_converter.convertToPhonem(word),
                                                   self.ipa_converter.convertToPhonem(match.heard)))
        return real_and_transcribed_words, real_and_transcribed_words_ipa, matches

    def getPronunciationAccuracy(self, matches) -> float:
        """The share of letters heard as written, per word and in all, from the
        words as said (WordMatch.real_canonical and heard_canonical): "2:30" is
        the letters of "two thirty"."""
        total_mismatches = 0.
        number_of_phonemes = 0.
        current_words_pronunciation_accuracy = []
        for match in matches:

            real_without_punctuation = match.real_canonical.replace(' ', '')
            number_of_word_mismatches = wm.edit_distance(
                real_without_punctuation, match.heard_canonical.replace(' ', ''))
            total_mismatches += number_of_word_mismatches
            number_of_phonemes_in_word = len(real_without_punctuation)
            number_of_phonemes += number_of_phonemes_in_word

            if number_of_phonemes_in_word > 0:
                current_words_pronunciation_accuracy.append(float(
                    number_of_phonemes_in_word-number_of_word_mismatches)/number_of_phonemes_in_word*100)
            else:
                current_words_pronunciation_accuracy.append(100.0)

        if number_of_phonemes > 0:
            percentage_of_correct_pronunciations = (
                number_of_phonemes-total_mismatches)/number_of_phonemes*100
        else:
            percentage_of_correct_pronunciations = 100.0

        return np.round(percentage_of_correct_pronunciations), current_words_pronunciation_accuracy

    def getWordsPronunciationCategory(self, accuracies, mistake_kinds=None) -> list:
        """0 (Correct), 1 (Almost) or 2 (Needs work) per word, from its share
        of letters heard as written. A word heard with a learner's typical
        mistake (mistake_kinds: WordMatching.known_mistake of each word, '' for
        none; an ending left out, th said as t, sh as s) is at best Almost,
        however many of its letters were heard."""
        categories = []

        for index, accuracy in enumerate(accuracies):
            category = int(self.getPronunciationCategoryFromAccuracy(accuracy))
            if category == 0 and mistake_kinds is not None and mistake_kinds[index]:
                category = 1
            categories.append(category)

        return categories

    def getPronunciationCategoryFromAccuracy(self, accuracy) -> int:
        return np.argmin(abs(self.categories_thresholds-accuracy))

    # The recording is scaled by a level that one loud click cannot set: its
    # loudest samples - 0.5% of them, and never more than 50 ms of them - are
    # left out, the next one is brought to 1/1.5 of full scale, and the few
    # above it (a tap on Record, the loudest syllables) are clipped. Scaled by
    # its peak, a short phrase spoken softly after a tap 30-50 dB louder
    # stayed too quiet for Whisper and was refused as no speech; a share of
    # the recording alone would clip a short phrase in a long take (one word
    # in 30 s).
    LEVEL_IGNORED_SHARE = 0.005
    LEVEL_IGNORED_SECONDS = 0.05
    LEVEL_HEADROOM = 1.5

    def preprocessAudio(self, audio: np.ndarray) -> np.ndarray:
        audio = audio-np.mean(audio)
        magnitudes = np.abs(audio).reshape(-1)
        level = 0.0
        if magnitudes.size:
            ignored = int(min(magnitudes.size * self.LEVEL_IGNORED_SHARE, self.LEVEL_IGNORED_SECONDS * self.sampling_rate))
            index = magnitudes.size - 1 - ignored
            level = float(np.partition(magnitudes, index)[index])
        if level > 0:
            audio = np.clip(audio / (level * self.LEVEL_HEADROOM), -1.0, 1.0)
        return audio.astype(np.float32, copy=False)
