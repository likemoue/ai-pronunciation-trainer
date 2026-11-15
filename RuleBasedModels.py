import functools
import os
import sqlite3
import threading

import ModelInterfaces


def get_phonem_converter(language: str):
    if language == 'de':
        import epitran  # only needed for German, which the English image does not install
        phonem_converter = EpitranPhonemConverter(
            epitran.Epitran('deu-Latn'))
    elif language == 'en':
        phonem_converter = EngPhonemConverter()
    else:
        raise ValueError('Language not implemented')

    return phonem_converter

class EpitranPhonemConverter(ModelInterfaces.ITextToPhonemModel):

    def __init__(self, epitran_model) -> None:
        super().__init__()
        self.epitran_model = epitran_model

    def convertToPhonem(self, sentence: str) -> str:
        phonem_representation = self.epitran_model.transliterate(sentence)
        return phonem_representation


class CmuIpa:
    """eng_to_ipa.convert, with the CMU Pronouncing Dictionary held in memory.

    eng_to_ipa opens its SQLite copy of the dictionary on every call and finds
    the words by reading all 133,779 rows (the table has no index on them):
    10-20 ms a call, and the scorer converts every word of the sentence and of
    the transcript on its own. This reads the rows once (about 0.6 s and 29 MB
    per process) and then runs eng_to_ipa's own steps on what it looks up, so
    the IPA is exactly eng_to_ipa.convert's (tests/test_ipa.py compares the
    two on every bank sentence).
    """

    def __init__(self, db_path=None):
        from eng_to_ipa import transcribe
        self._transcribe = transcribe
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(transcribe.__file__)),
                                   'resources', 'CMU_dict.db')
        entries = {}
        # Read-only, so the dictionary file in the image is never written.
        connection = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        try:
            for word, phonemes in connection.execute('SELECT word, phonemes FROM dictionary'):
                entries.setdefault(word, []).append(phonemes)
        finally:
            connection.close()
        if not entries:
            raise RuntimeError(f'The CMU dictionary at {db_path} is empty.')
        self._entries = {word: tuple(variants) for word, variants in entries.items()}
        # Bounded: transcripts can contain any word. 20,000 entries are a few MB.
        self.convert = functools.lru_cache(maxsize=20000)(self._convert)

    def __len__(self):
        return len(self._entries)

    def _get_cmu(self, tokens):
        # eng_to_ipa.transcribe.get_cmu, with the rows looked up in memory: each
        # known word gets all its pronunciations, an unknown one is marked to be
        # copied as it is.
        return [list(self._entries[token]) if token in self._entries else ['__IGNORE__' + token]
                for token in tokens]

    def _convert(self, text: str) -> str:
        # eng_to_ipa.convert(text) with its defaults: ipa_list(text, keep_punct=True,
        # stress_marks='both'), then get_top.
        t = self._transcribe
        words = [t.preserve_punc(w.lower())[0] for w in text.split()]
        ipa = t.cmu_to_ipa(self._get_cmu([w[1] for w in words]), stress_marking='both')
        ipa = t._punct_replace_word(words, ipa)
        return t.get_top(ipa)


_cmu_ipa = None
_cmu_ipa_lock = threading.Lock()


def cmu_ipa() -> CmuIpa:
    """The process's CmuIpa, loaded on first use."""
    global _cmu_ipa
    with _cmu_ipa_lock:
        if _cmu_ipa is None:
            _cmu_ipa = CmuIpa()
        return _cmu_ipa


class EngPhonemConverter(ModelInterfaces.ITextToPhonemModel):

    def __init__(self,) -> None:
        super().__init__()
        self._ipa = cmu_ipa()

    def convertToPhonem(self, sentence: str) -> str:
        phonem_representation = self._ipa.convert(sentence)
        phonem_representation = phonem_representation.replace('*','')
        return phonem_representation
