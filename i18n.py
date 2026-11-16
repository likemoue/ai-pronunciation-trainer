"""The interface's words in English and Vietnamese (context/design-system.md,
section 5: Language).

Each language has one dictionary, i18n/<language>.json: a flat JSON object of
"key": "text", in which {name} is a placeholder the page fills in. The server
renders the page in the learner's language (webApp.main, from the `lang`
cookie), so a Vietnamese learner never sees English first, and gives the page
both dictionaries, so that its script switches language in place.

The dictionaries are read once, at import, and must agree: the same keys, and
in each key the same placeholders. A worker whose dictionaries disagree does
not start (DictionaryError), rather than show a missing or half-filled text.
"""
import json
import os
import re
from collections import Counter

LANGUAGES = ('en', 'vi')
DEFAULT = 'en'
FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'i18n')

_PLACEHOLDER = re.compile(r'\{(\w+)\}')


class DictionaryError(ValueError):
    """A dictionary cannot be used: unreadable, not a flat object of strings,
    or not in agreement with the others."""


def placeholders(text: str) -> set:
    """The names of the placeholders in text: {'count'} for "{count} words"."""
    return set(_PLACEHOLDER.findall(text))


def _read(path: str) -> dict:
    """One dictionary: a flat JSON object of strings, each key once (json
    would keep the last of two silently). A byte order mark, which some
    Windows editors write, is allowed."""
    def each_key_once(pairs):
        twice = sorted(key for key, count in Counter(key for key, _ in pairs).items() if count > 1)
        if twice:
            raise DictionaryError(f'{path}: {", ".join(twice)} given twice')
        return dict(pairs)

    with open(path, encoding='utf-8-sig') as f:
        try:
            strings = json.load(f, object_pairs_hook=each_key_once)
        except json.JSONDecodeError as e:
            raise DictionaryError(f'{path}: {e}') from None
    if not isinstance(strings, dict) or not all(isinstance(text, str) for text in strings.values()):
        raise DictionaryError(f'{path}: not a flat object of strings')
    return strings


def load(folder: str = FOLDER, languages: tuple = LANGUAGES) -> dict:
    """Every language's dictionary, by language, from folder. Raises
    DictionaryError unless they all have the same keys, with the same
    placeholders in each key."""
    dictionaries = {language: _read(os.path.join(folder, f'{language}.json')) for language in languages}
    first, *others = languages
    reference = dictionaries[first]
    for language in others:
        strings = dictionaries[language]
        missing, extra = sorted(reference.keys() - strings.keys()), sorted(strings.keys() - reference.keys())
        if missing or extra:
            raise DictionaryError(f'{language}.json and {first}.json have different keys: '
                                  f'{language}.json lacks {missing} and adds {extra}')
        differ = sorted(key for key in reference if placeholders(reference[key]) != placeholders(strings[key]))
        if differ:
            raise DictionaryError(f'{language}.json and {first}.json have different placeholders in {differ}')
    return dictionaries


_DICTIONARIES = load()


def choose(value) -> str:
    """The interface language a request asks for (its `lang` cookie): the
    value itself when it is exactly one of LANGUAGES, else DEFAULT."""
    return value if value in LANGUAGES else DEFAULT


def dictionary(language: str) -> dict:
    """One language's dictionary (DEFAULT's for any other value): the
    template's `t`. Shared: do not change it."""
    return _DICTIONARIES[choose(language)]


def dictionaries() -> dict:
    """Every language's dictionary, by language: what the page's script gets
    (the i18nData block of templates/main.html). Shared: do not change it."""
    return _DICTIONARIES
