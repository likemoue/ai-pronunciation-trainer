import os
from dataclasses import dataclass


@dataclass
class LanguageConfig:
    asr_use_whisper: bool
    tts_speaker: str
    tts_sample_rate: int
    phonem_type: str
    phonem_args: dict
    csv_path: str
    asr_language: str


_REGISTRY = {
    'de': LanguageConfig(
        asr_use_whisper=True,
        tts_speaker='thorsten_v2',
        tts_sample_rate=16000,
        phonem_type='epitran',
        phonem_args={'language_code': 'deu-Latn'},
        csv_path='./databases/data_de.csv',
        asr_language='german',
    ),
    'en': LanguageConfig(
        asr_use_whisper=True,
        tts_speaker='lj_16khz',
        tts_sample_rate=16000,
        phonem_type='eng_to_ipa',
        phonem_args={},
        csv_path='./databases/data_en.csv',
        asr_language='english',
    ),
}

SUPPORTED_LANGUAGES = list(_REGISTRY.keys())

# Languages this deployment serves. Every enabled language loads its own ASR
# model, so the server only accepts the ones listed here (default: English).
ENABLED_LANGUAGES = [
    lang.strip() for lang in os.environ.get('ENABLED_LANGUAGES', 'en').split(',')
    if lang.strip() in _REGISTRY
] or ['en']


def is_enabled(language: str) -> bool:
    return language in ENABLED_LANGUAGES


def get(language: str) -> LanguageConfig:
    if language not in _REGISTRY:
        raise ValueError(f'Language "{language}" not supported. Available: {SUPPORTED_LANGUAGES}')
    return _REGISTRY[language]
