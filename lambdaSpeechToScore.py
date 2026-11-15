
import json
import math
import os
import threading
import WordMatching as wm
import pronunciationTrainer
import base64
import time

import numpy as np

import audioPreprocessing
import logging_setup

logger = logging_setup.get_logger(__name__)


class NoSpeechError(Exception):
    """The recording contained no recognisable speech."""


class ServerBusyError(Exception):
    """This worker holds as many recordings as it takes; try again later."""

    def __init__(self, retry_after: int):
        super().__init__(f'The server is busy; try again in {retry_after} s.')
        self.retry_after = retry_after


class ClientGoneError(Exception):
    """The client closed its connection while its recording waited."""


class ScoringQueue:
    """Admission control for the recordings of one worker.

    A worker scores one recording at a time (_inference_lock), and each
    recording waiting for it holds a gunicorn thread. A recording is turned
    away, before it is decoded, when the worker already holds `limit` of them
    or when those ahead of it would take more than `max_wait` seconds, judged
    from how long a recording has held the model recently. So
    GUNICORN_THREADS - limit threads stay free for the page, the samples and
    the reference voice, and no recording waits anywhere near Cloudflare's
    125 s. The client tries again after Retry-After.
    """

    def __init__(self, limit: int, max_wait: float, initial_seconds: float = 1.0):
        self.limit = limit
        self.max_wait = max_wait
        self._lock = threading.Lock()
        self._pending = 0
        # A guess until recordings have been timed: faster-whisper holds the
        # model for 0.5-1.2 s per recording on the production VM.
        self._seconds = initial_seconds

    def admit(self) -> int:
        """Take a place, or raise ServerBusyError. Returns the number of
        recordings ahead of this one."""
        with self._lock:
            ahead = self._pending
            if ahead >= self.limit or ahead * self._seconds > self.max_wait:
                # Roughly when the recordings held now will have been scored.
                raise ServerBusyError(max(1, min(30, math.ceil(ahead * self._seconds))))
            self._pending += 1
            return ahead

    def release(self, held_seconds=None):
        """Give the place back; held_seconds is how long the recording held the
        model (None: not timed, as for the warm-up, whose first pass through a
        cold model takes several times longer than any later one)."""
        with self._lock:
            self._pending -= 1
            if held_seconds is not None:
                self._seconds += 0.3 * (held_seconds - self._seconds)

    @property
    def pending(self) -> int:
        return self._pending

    @property
    def seconds_per_recording(self) -> float:
        return self._seconds


def _queue_limit(environ) -> int:
    """SCORING_QUEUE_LIMIT, else 4 fewer than the worker's gunicorn threads
    (gunicorn.conf.py), which leaves 2 for speech synthesis and 2 for the rest."""
    if environ.get('SCORING_QUEUE_LIMIT'):
        return max(1, int(environ['SCORING_QUEUE_LIMIT']))
    return max(1, int(environ.get('GUNICORN_THREADS', '24')) - 4)


_queue = ScoringQueue(limit=_queue_limit(os.environ),
                      max_wait=float(os.environ.get('SCORING_MAX_WAIT_SECONDS', '30')))


SILENCE_PEAK_THRESHOLD = 0.003

# Short sentences used to warm up and self-check the scoring pipeline. They
# contain the one-letter words "I" and "a", which take their own code path in
# the word alignment. Whisper hears the LJ Speech voice's "Hello" as "Below"
# about half the time, so the English sentence starts with "I" (100% in 30 of
# 30 syntheses).
WARMUP_SENTENCES = {
    'en': 'I have a cat and a dog at home.',
    'de': 'Hallo, ich habe eine Katze und einen Hund.',
}

_trainer_cache = {}
_trainer_cache_lock = threading.Lock()
# The trainer and the ASR wrapper keep per-call state (transcript, word
# locations) on the instance, so concurrent requests must not interleave.
_inference_lock = threading.Lock()


def _get_trainer(language):
    with _trainer_cache_lock:
        if language not in _trainer_cache:
            _trainer_cache[language] = pronunciationTrainer.getTrainer(language)
        return _trainer_cache[language]


def warm_up(language, strict=None) -> bool:
    """Load the trainer, then score one short spoken sentence so first-call
    costs (Whisper's first forward pass, JIT compilation in the word alignment,
    the IPA dictionary) are paid at start-up instead of by the first user.

    The sentence is synthesised with Piper. Real speech keeps Whisper on its
    normal path; noise would make it decode the maximum number of tokens.

    Returns True when the pass produced a sensible score. With strict=True (or
    WARMUP_STRICT=1, used by the Docker build) any failure raises instead, so a
    broken scoring pipeline fails the build rather than shipping.
    """
    if strict is None:
        strict = os.environ.get('WARMUP_STRICT') == '1'
    try:
        _get_trainer(language)
        import piperTTS
        sentence = WARMUP_SENTENCES.get(language)
        if sentence is None or not piperTTS.is_available() or language not in piperTTS.VOICE_CONFIGS:
            raise RuntimeError(f'No warm-up voice for language "{language}"')
        audio = base64.b64decode(piperTTS.generate_wav_base64(sentence, language))
        start = time.perf_counter()
        result = score(sentence, audio, language, warm_up=True)
        accuracy = int(result['pronunciation_accuracy'])
        if accuracy < 50:
            raise RuntimeError(f'Warm-up sentence scored only {accuracy}% '
                               f'(heard: {result["real_transcript"]!r})')
        logger.info('warm-up scoring pass ok', extra={'fields': {
            'event': 'warmup', 'language': language, 'accuracy': accuracy,
            'seconds': round(time.perf_counter() - start, 1)}})
        return True
    except Exception as e:
        if strict:
            raise
        logger.error('WARM-UP FAILED for %s: %r', language, e)
        return False


def score(real_text: str, audio_bytes: bytes, language: str, client_gone=None, *, warm_up=False) -> dict:
    """Score one recording of real_text. Raises NoSpeechError when nothing was
    said, audioPreprocessing.AudioDecodeError / AudioTooLongError for unusable
    uploads, ServerBusyError when this worker holds too many recordings, and
    ClientGoneError when client_gone() says, once the model is free, that
    nobody is waiting for the answer any more. The warm-up (warm_up=True) takes
    no place in the queue, since it must run even when learners fill it, and
    its time, a cold model's first pass, stays out of the queue's estimate."""
    if not real_text.strip():
        raise ValueError('There is no sentence to compare with.')

    started = time.perf_counter()
    stats = {'event': 'score', 'language': language, 'upload_kb': round(len(audio_bytes) / 1024, 1),
             'words': len(real_text.split())}
    admitted = False
    held_seconds = None
    try:
        if not warm_up:
            stats['queue_ahead'] = _queue.admit()
            admitted = True
        signal = audioPreprocessing.decode_audio(audio_bytes, target_rate=16000)
        stats['decode_ms'] = round((time.perf_counter() - started) * 1000)
        stats['audio_s'] = round(signal.shape[-1] / 16000, 2)
        # A muted or disconnected microphone produces (near) digital silence. Do not
        # send it to Whisper, which would hallucinate text for it.
        if signal.size == 0 or float(np.abs(signal).max()) < SILENCE_PEAK_THRESHOLD:
            raise NoSpeechError()

        trainer = _get_trainer(language)
        waiting = time.perf_counter()
        with _inference_lock:
            stats['lock_wait_ms'] = round((time.perf_counter() - waiting) * 1000)
            if client_gone is not None and client_gone():
                raise ClientGoneError()
            holding = time.perf_counter()
            try:
                result = trainer.processAudioForGivenText(signal, real_text)
            finally:
                held_seconds = time.perf_counter() - holding
        stats.update({f'{name}_ms': value for name, value in result.get('timings_ms', {}).items()})
        if not result['recording_transcript'].strip():
            raise NoSpeechError()
        response = _build_response(result)
        stats['accuracy'] = int(response['pronunciation_accuracy'])
        stats['outcome'] = 'ok'
        return response
    except ServerBusyError as e:
        stats['outcome'] = 'busy'
        stats['retry_after_s'] = e.retry_after
        raise
    except ClientGoneError:
        stats['outcome'] = 'client_gone'
        raise
    except NoSpeechError:
        stats['outcome'] = 'no_speech'
        raise
    except audioPreprocessing.AudioTooLongError:
        stats['outcome'] = 'too_long'
        raise
    except audioPreprocessing.AudioDecodeError:
        stats['outcome'] = 'bad_audio'
        raise
    except Exception:
        stats['outcome'] = 'error'
        raise
    finally:
        if admitted:
            _queue.release(held_seconds)
        stats['total_ms'] = round((time.perf_counter() - started) * 1000)
        logger.info('scored', extra={'fields': stats})


def _build_response(result) -> dict:
    """Shape the trainer's result into the JSON the frontend expects."""
    real_transcripts_ipa = ' '.join(
        [word[0] for word in result['real_and_transcribed_words_ipa']])
    matched_transcripts_ipa = ' '.join(
        [word[1] for word in result['real_and_transcribed_words_ipa']])

    real_transcripts = ' '.join(
        [word[0] for word in result['real_and_transcribed_words']])
    matched_transcripts = ' '.join(
        [word[1] for word in result['real_and_transcribed_words']])

    words_real = real_transcripts.lower().split()
    mapped_words = matched_transcripts.split()

    is_letter_correct_all_words = ''
    for idx, word_real in enumerate(words_real):

        mapped_letters, mapped_letters_indices = wm.get_best_mapped_words(
            mapped_words[idx], word_real)

        is_letter_correct = wm.getWhichLettersWereTranscribedCorrectly(
            word_real, mapped_letters)

        is_letter_correct_all_words += ''.join([str(is_correct)
                                                for is_correct in is_letter_correct]) + ' '

    pair_accuracy_category = ' '.join(
        [str(category) for category in result['pronunciation_categories']])

    return {'real_transcript': result['recording_transcript'],
            'ipa_transcript': result['recording_ipa'],
            'pronunciation_accuracy': str(int(result['pronunciation_accuracy'])),
            'real_transcripts': real_transcripts, 'matched_transcripts': matched_transcripts,
            'real_transcripts_ipa': real_transcripts_ipa, 'matched_transcripts_ipa': matched_transcripts_ipa,
            'pair_accuracy_category': pair_accuracy_category,
            'start_time': result['start_time'],
            'end_time': result['end_time'],
            'is_letter_correct_all_words': is_letter_correct_all_words}


def lambda_handler(event, context):
    """AWS-Lambda-style entry point kept for scripts and tests."""
    data = json.loads(event['body'])
    base64_audio = data['base64Audio']
    if base64_audio.startswith('data:'):
        base64_audio = base64_audio.partition(',')[2]
    return json.dumps(score(data['title'], base64.b64decode(base64_audio), data['language']))
