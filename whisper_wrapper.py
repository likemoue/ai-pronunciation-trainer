"""Speech recognition with Whisper base, run by CTranslate2 (faster-whisper).

The weights are those of openai/whisper-base, converted to CTranslate2 by
Systran (model_pins.WHISPER_*) and quantised to int8 when they are
loaded. Compared with the transformers pipeline the app used before, with
the same settings (greedy decoding, the language pinned to English, word
timestamps), a recording is transcribed 2.5 to 5 times faster, in about a
tenth of the memory, and noise gives an empty transcript instead of an
invented sentence: a window that Whisper rates as probably not speech, with
little confidence in its words, is dropped.
"""
import os
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


class WhisperASRModel(IASRModel):
    def __init__(self, model_dir: Optional[str] = None, language: Optional[str] = None):
        # Imported here: the first import of onnxruntime must be piperTTS's
        # (CLAUDE.md), and faster_whisper's VAD would import it.
        import piperTTS
        piperTTS.import_onnxruntime()
        from faster_whisper import WhisperModel

        model_dir = model_dir or os.environ.get('WHISPER_MODEL') or DEFAULT_MODEL_DIR
        if not os.path.isfile(os.path.join(model_dir, 'model.bin')):
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
            # The silence threshold also drops what Whisper invents in a long
            # pause, as it did for one recording of noise alone.
            without_timestamps=False, word_timestamps=True, hallucination_silence_threshold=2.0,
            max_new_tokens=self.max_new_tokens)
        # The transcript is built from the timed words, so its words and the
        # word locations always line up one to one: the trainer indexes both
        # the same way. Whisper attaches punctuation to the word before it.
        timed = [(text, word.start, word.end) for segment in segments for word in (segment.words or [])
                 for text in word.word.split()]
        self._transcript = ' '.join(text for text, _, _ in timed)
        self._word_locations = [{'word': text,
                                 'start_ts': start * self.sample_rate,
                                 'end_ts': end * self.sample_rate,
                                 'tag': 'processed'} for text, start, end in timed]

    def getTranscript(self) -> str:
        return self._transcript

    def getWordLocations(self) -> list:
        return self._word_locations
