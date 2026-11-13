"""Input validation shared by every API route.

Everything that reaches the scoring, sampling or TTS code goes through these
helpers first. They keep each request bounded (text length, word count, audio
size), so a single anonymous request cannot tie up a worker for minutes.
"""
import base64
import binascii
import os
import re
import unicodedata


class ValidationError(ValueError):
    """A request the server refuses. The message is safe to show to the user."""

    def __init__(self, message: str, status: int = 400, code: str = 'invalid_request'):
        super().__init__(message)
        self.status = status
        self.code = code


MAX_TEXT_CHARS = int(os.environ.get('MAX_CUSTOM_TEXT_CHARS', '300'))
MAX_TEXT_WORDS = int(os.environ.get('MAX_TEXT_WORDS', '60'))
# Share of letters that must be plain A-Z. Practice texts are English; this
# keeps CJK and other scripts away from the phonemiser and the TTS voice.
MIN_LATIN_LETTER_RATIO = 0.9
# The player reads single words of a practice sentence aloud. Those can be a
# number ("2:30") or a name with accents ("André"), which a whole sentence may
# contain but which fail the letter-ratio check on their own.
MAX_SINGLE_WORD_CHARS = 20
CATEGORIES = (0, 1, 2, 3)  # 0 = random, 1 = easy, 2 = medium, 3 = hard

_TYPOGRAPHY = str.maketrans({
    '‘': "'", '’': "'", '‛': "'", '′': "'",
    '“': '"', '”': '"', '‟': '"', '″': '"',
    '–': ' - ', '—': ' - ', '−': ' - ', '…': '...',
})


def normalize_text(text: str) -> str:
    """Collapse whitespace, straighten typographic quotes/dashes and drop
    tokens that contain no letters or digits (they cannot be pronounced and
    would break the word-by-word alignment).

    The function is idempotent, and the frontend applies the same rules, so
    the words the browser shows and the words the server scores stay in step.
    """
    text = (text or '').translate(_TYPOGRAPHY)
    tokens = [token for token in text.split() if any(ch.isalnum() for ch in token)]
    return ' '.join(tokens)


def latin_letter_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if 'a' <= ch.lower() <= 'z') / len(letters)


# Control characters (NUL makes espeak-ng fail) and lone UTF-16 surrogates:
# JSON allows "\ud800", and the phonemiser, sqlite and hashlib cannot encode it.
_UNREADABLE = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]')


def _require_readable(text: str) -> None:
    if _UNREADABLE.search(text):
        raise ValidationError('The text contains hidden characters that cannot be read. '
                              'Please type it again or paste it as plain text.', code='text_bad_characters')


def practice_text(value, *, empty_message: str = 'Please type at least one word.') -> str:
    """Validate a reference sentence or a text to read aloud and return it normalised."""
    if not isinstance(value, str):
        raise ValidationError(empty_message)
    text = normalize_text(value)
    if not text:
        raise ValidationError(empty_message)
    if len(text) > MAX_TEXT_CHARS:
        raise ValidationError(f'Please keep the text under {MAX_TEXT_CHARS} characters.',
                              code='text_too_long')
    if len(text.split()) > MAX_TEXT_WORDS:
        raise ValidationError(f'Please keep the text under {MAX_TEXT_WORDS} words.',
                              code='text_too_long')
    _require_readable(text)
    if latin_letter_ratio(text) < MIN_LATIN_LETTER_RATIO:
        raise ValidationError('Please type English text (Latin letters).', code='text_not_english')
    return text


def _is_latin_word(word: str) -> bool:
    """True if every letter is A-Z once accents are removed (digits are fine)."""
    letters = [ch for ch in unicodedata.normalize('NFKD', word)
               if ch.isalpha() and not unicodedata.combining(ch)]
    return all('a' <= ch.lower() <= 'z' for ch in letters)


def speech_text(value, *, empty_message: str = 'No text to read.') -> str:
    """Validate a text for the TTS route: a practice text, or one short word
    from one (which may be a number or an accented name)."""
    if isinstance(value, str):
        word = normalize_text(value)
        if word and ' ' not in word and len(word) <= MAX_SINGLE_WORD_CHARS and _is_latin_word(word):
            _require_readable(word)
            return word
    return practice_text(value, empty_message=empty_message)


def category(value) -> int:
    """Validate the difficulty category sent by /getSample."""
    if isinstance(value, bool):
        raise ValidationError('Unknown sentence category.', code='bad_category')
    if isinstance(value, float) and not value.is_integer():
        raise ValidationError('Unknown sentence category.', code='bad_category')
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError('Unknown sentence category.', code='bad_category')
    if number not in CATEGORIES:
        raise ValidationError('Unknown sentence category.', code='bad_category')
    return number


def audio_bytes(value) -> bytes:
    """Decode the base64 recording (optionally a data: URL) sent by the browser."""
    if not isinstance(value, str) or not value:
        raise ValidationError('No audio was received.', code='no_audio')
    # Strip the data-URL header ("data:audio/ogg;base64,") whatever its length.
    if value.startswith('data:'):
        _, _, value = value.partition(',')
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError('The recording could not be read. Please try again.', code='bad_audio')
    if not raw:
        raise ValidationError('No audio was received.', code='no_audio')
    return raw
