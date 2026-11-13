
import json
import os
import threading
import WordMatching as wm
import pronunciationTrainer
import base64
import time
import audioPreprocessing


class NoSpeechError(Exception):
    """The recording contained no recognisable speech."""


SILENCE_PEAK_THRESHOLD = 0.003

# Short sentences used to warm up and self-check the scoring pipeline. They
# contain the one-letter words "I" and "a", which take their own code path in
# the word alignment.
WARMUP_SENTENCES = {
    'en': 'Hello, I have a cat and a dog at home.',
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
        start = time.time()
        result = score(sentence, audio, language)
        accuracy = int(result['pronunciation_accuracy'])
        if accuracy < 50:
            raise RuntimeError(f'Warm-up sentence scored only {accuracy}% '
                               f'(heard: {result["real_transcript"]!r})')
        print(f'Warm-up scoring pass OK for "{language}": {accuracy}% in {time.time() - start:.1f} s')
        return True
    except Exception as e:
        if strict:
            raise
        print(f'WARM-UP FAILED for "{language}": {e!r}')
        return False


def score(real_text: str, audio_bytes: bytes, language: str) -> dict:
    """Score one recording of real_text. Raises NoSpeechError when nothing was
    said, and audioPreprocessing.AudioDecodeError / AudioTooLongError for
    unusable uploads."""
    if not real_text.strip():
        raise ValueError('There is no sentence to compare with.')

    signal = audioPreprocessing.decode_audio(audio_bytes, target_rate=16000)
    # A muted or disconnected microphone produces (near) digital silence. Do not
    # send it to Whisper, which would hallucinate text for it.
    if signal.numel() == 0 or float(signal.abs().max()) < SILENCE_PEAK_THRESHOLD:
        raise NoSpeechError()

    trainer = _get_trainer(language)
    with _inference_lock:
        try:
            result = trainer.processAudioForGivenText(signal, real_text)
        except Exception:
            if not trainer.asr_model.getTranscript().strip():
                raise NoSpeechError()
            raise
    if not result['recording_transcript'].strip():
        raise NoSpeechError()

    start = time.time()
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
    print('Time to post-process results: ', str(time.time()-start))

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
