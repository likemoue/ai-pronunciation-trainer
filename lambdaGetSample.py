
import hashlib
import json
import random
import re
import threading

import pandas as pd

import RuleBasedModels
import language_registry
import piperTTS
import validation


AUDIO_KEY = re.compile(r'[0-9a-f]{16}')


def audio_key(sentence: str, voice: str) -> str:
    """The name of a bank sentence's recording (/tts/<language>/<key>.mp3). It
    depends on the sentence and the voice only, so the URL stays the same from
    one release to the next and changes with the voice: browsers and
    Cloudflare can keep the file for good."""
    return hashlib.sha256('\n'.join((voice, sentence)).encode('utf-8')).hexdigest()[:16]


class SentenceBank:
    """Practice sentences of one language, pre-sorted by difficulty category."""

    def __init__(self, sentences, voice=''):
        # Normalise once at load time with the same rules as custom text, so the
        # sentence the browser shows is exactly the one the scorer receives back.
        self.sentences = [validation.normalize_text(str(s)) for s in sentences]
        self.sentences = [s for s in self.sentences if s]
        self.by_category = {0: list(range(len(self.sentences)))}
        for category in (1, 2, 3):
            self.by_category[category] = []
        for idx, sentence in enumerate(self.sentences):
            self.by_category[getSentenceCategory(sentence)].append(idx)
        self.voice = voice
        self.keys = [audio_key(sentence, voice) for sentence in self.sentences]
        self.by_key = dict(zip(self.keys, self.sentences, strict=True))

    def pick(self, category: int) -> int:
        """The index of a random sentence of the category."""
        indices = self.by_category.get(category)
        if not indices:
            raise ValueError(f'No sentences in category {category}.')
        return random.choice(indices)

    def __len__(self):
        return len(self.sentences)


_database_cache = {}
_ipa_converter_cache = {}
_init_lock = threading.Lock()


def _ensure_initialized(language):
    """Load the sentence database and IPA converter for one language on first use."""
    with _init_lock:
        if language in _database_cache:
            return
        config = language_registry.get(language)
        df = pd.read_csv(config.csv_path, delimiter=';')
        _ipa_converter_cache[language] = RuleBasedModels.get_phonem_converter(language)
        _database_cache[language] = SentenceBank(df['sentence'].tolist(),
                                                 voice=piperTTS.VOICE_CONFIGS.get(language, ''))


def sample(category: int, language: str) -> dict:
    """Pick a random practice sentence. category: 0 = any, 1 = easy, 2 = medium, 3 = hard."""
    category = validation.category(category)
    _ensure_initialized(language)
    bank = _database_cache[language]
    index = bank.pick(category)
    sentence = bank.sentences[index]
    return {'real_transcript': [sentence],
            'ipa_transcript': _ipa_converter_cache[language].convertToPhonem(sentence),
            'transcript_translation': '',
            # The reference voice for this sentence, as a cacheable MP3 (webApp.py).
            'tts_url': f'/tts/{language}/{bank.keys[index]}.mp3'}


def sentence_for_audio_key(language: str, key: str):
    """The bank sentence whose recording is named key, or None."""
    if not AUDIO_KEY.fullmatch(key or ''):
        return None
    _ensure_initialized(language)
    return _database_cache[language].by_key.get(key)


def lambda_handler(event, context):
    body = json.loads(event['body'])
    return json.dumps(sample(body.get('category'), body['language']))


MAX_CUSTOM_TEXT_CHARS = validation.MAX_TEXT_CHARS

# Kept for callers that import it from here.
normalize_custom_text = validation.normalize_text


def custom_sample(text: str, language: str) -> dict:
    """Build a practice sample from user-provided text. Raises ValueError with a
    user-facing message when the text cannot be used."""
    text = validation.practice_text(text)
    _ensure_initialized(language)
    ipa = _ipa_converter_cache[language].convertToPhonem(text)
    return {'real_transcript': [text],
            'ipa_transcript': ipa,
            'transcript_translation': ''}


def getSentenceCategory(sentence) -> int:
    number_of_words = len(sentence.split())
    categories_word_limits = [0, 8, 20, 100000]
    for category in range(len(categories_word_limits)-1):
        if number_of_words > categories_word_limits[category] and number_of_words <= categories_word_limits[category+1]:
            return category+1
    return 1
