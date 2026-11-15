"""Speech recognition with Whisper base, run by CTranslate2 (faster-whisper).

The weights are those of openai/whisper-base, converted to CTranslate2 by
Systran (model_pins.WHISPER_*) and quantised to int8 when they are
loaded. Compared with the transformers pipeline the app used before, with
the same settings (greedy decoding, the language pinned to English, word
timestamps), a recording is transcribed about twice as fast, in a fraction
of the memory, and noise usually gives an empty transcript instead of an
invented sentence: a window that Whisper rates as probably not speech is
dropped.
"""
import os
import re
from typing import Optional

import numpy as np

import logging_setup
import model_pins
from ModelInterfaces import IASRModel

logger = logging_setup.get_logger(__name__)

# The Docker image has the model in /models/faster-whisper-base (WHISPER_MODEL);
# a development checkout downloads it to models/faster-whisper-base on first use.
DEFAULT_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', 'faster-whisper-base')


def _int_env(name, default):
    value = os.environ.get(name)
    return int(value) if value else default


def words_and_locations(words, sample_rate=16000):
    """The transcript and one location per word of it, from Whisper's timed
    words [(text, start s, end s)].

    The transcript is Whisper's text as it wrote it, its words being what the
    trainer gets from transcript.split(). Whisper's word list is cut
    differently: "well-known", "o'clock" or "2:30" come as two timed words, the
    second without a space before it. Each word of the transcript gets the
    span of the timed words it is made of, so the two lists line up one to one
    (the trainer indexes both the same way).
    """
    text = ''
    spans = []  # (first char, end char, start s, end s) of each timed word
    for word, start, end in words:
        spans.append((len(text), len(text) + len(word), start, end))
        text += word
    transcript_words, locations = [], []
    for match in re.finditer(r'\S+', text):
        times = [(start, end) for first, last, start, end in spans if first < match.end() and last > match.start()]
        start, end = min(t[0] for t in times), max(t[1] for t in times)
        transcript_words.append(match.group())
        locations.append({'word': match.group(), 'start_ts': start * sample_rate, 'end_ts': end * sample_rate,
                          'tag': 'processed'})
    return ' '.join(transcript_words), locations


class WhisperASRModel(IASRModel):
    def __init__(self, model_dir: Optional[str] = None, language: Optional[str] = None):
        # Imported here: the first import of onnxruntime must be piperTTS's
        # (CLAUDE.md), and faster_whisper's VAD would import it.
        import piperTTS
        piperTTS.import_onnxruntime()
        from faster_whisper import WhisperModel

        model_dir = model_dir or os.environ.get('WHISPER_MODEL') or DEFAULT_MODEL_DIR
        # Any file missing (a first download that was interrupted) is fetched;
        # the files already there are checked against their sha256.
        if not all(os.path.isfile(os.path.join(model_dir, name)) for name in model_pins.WHISPER_FILES):
            for name in model_pins.download_whisper(model_dir):
                logger.info('Downloaded Whisper file %s', name)
        # Each gunicorn worker scores one recording at a time (lambdaSpeechToScore),
        # so one CTranslate2 replica with WHISPER_CPU_THREADS threads; workers x
        # threads should not exceed the CPUs (Dockerfile: 2 x 5 on 10 cores).
        self.model = WhisperModel(
            model_dir, device='cpu',
            compute_type=os.environ.get('WHISPER_COMPUTE_TYPE', 'int8'),
            cpu_threads=_int_env('WHISPER_CPU_THREADS', _int_env('OMP_NUM_THREADS', 4)),
            num_workers=1, local_files_only=True)
        self.language = language or 'en'
        # Cap the output length: on silence or noise Whisper can repeat the same
        # phrase until the window ends. 160 tokens comfortably cover a
        # 300-character practice text.
        self.max_new_tokens = _int_env('WHISPER_MAX_NEW_TOKENS', 160)
        self.sample_rate = 16000
        self._transcript = ''
        self._word_locations = []

    def processAudio(self, audio):
        """audio: float32 samples at 16 kHz, shape [1, samples]."""
        # Nothing of the previous recording may stay if this one fails.
        self._transcript = ''
        self._word_locations = []
        samples = np.ascontiguousarray(np.asarray(audio, dtype=np.float32).reshape(-1))
        segments, _ = self.model.transcribe(
            samples, language=self.language, task='transcribe',
            # Greedy decoding without temperature fallback, as the transformers
            # pipeline decoded: the same input always gives the same transcript.
            beam_size=1, best_of=1, temperature=0.0,
            condition_on_previous_text=False,
            # Whisper's own timestamps end the text where the speech ends.
            # Without them it added a word ("you", "Thank you.") after the
            # sentence in 52 of 124 test recordings that end in half a second
            # of silence; with them, in none, and it ran three times faster.
            # (hallucination_silence_threshold is not used: it also dropped a
            # single real word followed by a pause.)
            without_timestamps=False, word_timestamps=True,
            # A window that Whisper rates as probably not speech
            # (no_speech_prob > 0.6) is skipped however sure it is of the words
            # it would write. By default a confident enough invention is kept:
            # noise recorded by the page (WebM/Opus) came back as "I'm going to
            # get a little bit of a". In the tests, noise was rated 0.65-0.80,
            # and sentences of three words or more at a normal level 0.46 at
            # most. A short phrase spoken very softly can go above 0.6 (up to
            # 0.66) and is refused as no speech, which asks the learner to
            # speak louder: the recording is scaled by its peak
            # (preprocessAudio), so a tap on the phone far louder than the
            # voice makes the voice quieter still.
            no_speech_threshold=0.6, log_prob_threshold=None,
            max_new_tokens=self.max_new_tokens)
        self._transcript, self._word_locations = words_and_locations(
            [(word.word, word.start, word.end) for segment in segments for word in (segment.words or [])],
            self.sample_rate)

    def getTranscript(self) -> str:
        return self._transcript

    def getWordLocations(self) -> list:
        return self._word_locations
