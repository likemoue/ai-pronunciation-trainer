
import json
import threading
import WordMatching as wm
import pronunciationTrainer
import base64
import time
import audioPreprocessing

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


def warm_up(language):
    """Load the trainer (ASR model + phoneme converter) ahead of the first request."""
    _get_trainer(language)


def lambda_handler(event, context):

    data = json.loads(event['body'])

    real_text = data['title']
    base64_audio = data['base64Audio']
    # Strip the data-URL header ("data:audio/ogg;base64,") whatever its length.
    if ',' in base64_audio[:100]:
        base64_audio = base64_audio.split(',', 1)[1]
    file_bytes = base64.b64decode(base64_audio.encode('utf-8'))
    language = data['language']

    if len(real_text) == 0:
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Allow-Credentials': "true",
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'OPTIONS,POST,GET'
            },
            'body': ''
        }

    signal = audioPreprocessing.decode_audio(file_bytes, target_rate=16000)

    trainer = _get_trainer(language)
    with _inference_lock:
        result = trainer.processAudioForGivenText(signal, real_text)

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

    res = {'real_transcript': result['recording_transcript'],
           'ipa_transcript': result['recording_ipa'],
           'pronunciation_accuracy': str(int(result['pronunciation_accuracy'])),
           'real_transcripts': real_transcripts, 'matched_transcripts': matched_transcripts,
           'real_transcripts_ipa': real_transcripts_ipa, 'matched_transcripts_ipa': matched_transcripts_ipa,
           'pair_accuracy_category': pair_accuracy_category,
           'start_time': result['start_time'],
           'end_time': result['end_time'],
           'is_letter_correct_all_words': is_letter_correct_all_words}

    return json.dumps(res)
