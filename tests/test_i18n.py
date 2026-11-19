"""The interface language: the page in English or Vietnamese from the `lang`
cookie (webApp.main), and the dictionaries (i18n.py, i18n/*.json) that the
template and the page's script read."""
import html.parser
import importlib.util
import json
import os
import re
import shutil
import unicodedata

import pytest

import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EN_DESCRIPTION = 'Practise English pronunciation with instant AI feedback on every word.'


class Scripts(html.parser.HTMLParser):
    """The <script> elements of a page: their attributes and their text."""

    def __init__(self, page):
        super().__init__()
        self.scripts = []
        self._open = None
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self._open = {'attrs': dict(attrs), 'text': ''}
            self.scripts.append(self._open)

    def handle_data(self, data):
        if self._open is not None:
            self._open['text'] += data

    def handle_endtag(self, tag):
        if tag == 'script':
            self._open = None


def get_page(client, lang=None):
    """GET / with this `lang` cookie (None: no cookie)."""
    if lang is not None:
        client.set_cookie('lang', lang)
    return client.get('/')


def test_the_module_is_i18n_py_beside_its_folder_of_dictionaries():
    # i18n/ has no __init__.py: a folder without one never hides a module of its name.
    assert os.path.basename(i18n.__file__) == 'i18n.py'
    assert not os.path.exists(os.path.join(i18n.FOLDER, '__init__.py'))
    assert all(os.path.isfile(os.path.join(i18n.FOLDER, f'{language}.json')) for language in i18n.LANGUAGES)
    assert i18n.LANGUAGES == ('en', 'vi') and i18n.DEFAULT == 'en'


def test_the_page_is_in_english_by_default(client):
    page = get_page(client).get_data(as_text=True)
    assert '<html lang="en">' in page
    assert f'<meta name="description" content="{EN_DESCRIPTION}">' in page
    assert '<title>AI Pronunciation Trainer</title>' in page


def test_the_lang_cookie_gives_the_page_in_vietnamese(client):
    page = get_page(client, 'vi').get_data(as_text=True)
    assert '<html lang="vi">' in page
    assert '<meta name="description" content="Luyện phát âm tiếng Anh, máy chấm ngay từng từ bạn đọc.">' in page
    assert '<title>AI Pronunciation Trainer</title>' in page  # the product's name in both


@pytest.mark.parametrize('value', ['en', '', 'VI', 'Vi', 'vi-VN', 'vie', 'fr', 'en,vi', 'vi_VN'])
def test_any_other_cookie_value_gives_the_page_in_english(client, value):
    page = get_page(client, value).get_data(as_text=True)
    assert '<html lang="en">' in page and EN_DESCRIPTION in page


@pytest.mark.parametrize('lang', [None, 'vi'])
def test_the_page_varies_with_the_cookie_and_is_checked_on_every_load(client, lang):
    response = get_page(client, lang)
    assert response.headers['Cache-Control'] == 'no-cache'
    assert 'cookie' in [name.strip().lower() for name in response.headers['Vary'].split(',')]


@pytest.mark.parametrize('lang', ['en', 'vi'])
def test_every_script_is_a_file_or_a_data_block_and_the_data_holds_both_languages(client, lang):
    # A data block is never executed, so the CSP (script-src 'self', no inline scripts) still holds.
    response = get_page(client, lang)
    assert "'unsafe-inline'" not in response.headers['Content-Security-Policy']
    scripts = Scripts(response.get_data(as_text=True)).scripts
    for script in scripts:
        if 'src' in script['attrs']:
            assert not script['text'].strip(), script
        else:
            assert script['attrs'].get('type') == 'application/json', script['attrs']
    ids = [script['attrs'].get('id') for script in scripts]
    assert ids.count('i18nData') == 1
    data = json.loads(scripts[ids.index('i18nData')]['text'])
    assert data == {'en': i18n.dictionary('en'), 'vi': i18n.dictionary('vi')}
    # Before the first script, which reads it.
    assert ids.index('i18nData') < min(i for i, script in enumerate(scripts) if 'src' in script['attrs'])


def test_a_text_with_markup_stays_inside_the_data_block(client, monkeypatch):
    sneaky = dict(i18n.dictionary('en'))
    sneaky['page.description'] = '</script><script>alert(1)</script><!-- & \'"'
    # A text with an element in it (the template's rich macro): the text around the slot is escaped.
    sneaky['how.step1'] = '<img src=x onerror=alert(1)> {slow} </p><script>alert(2)</script>'
    monkeypatch.setattr(i18n, '_DICTIONARIES', {'en': sneaky, 'vi': sneaky})
    page = get_page(client).get_data(as_text=True)
    scripts = Scripts(page).scripts
    assert [script['attrs'].get('type') for script in scripts if 'src' not in script['attrs']] == ['application/json']
    data = next(script for script in scripts if script['attrs'].get('id') == 'i18nData')
    assert json.loads(data['text']) == {'en': sneaky, 'vi': sneaky}
    outside_the_data = page.replace(data['text'], '')
    assert '<img' not in outside_the_data and 'alert(2)</script>' not in outside_the_data
    assert ('&lt;img src=x onerror=alert(1)&gt; <b data-slot="slow" data-i18n="card.slow">Slow</b> '
            '&lt;/p&gt;&lt;script&gt;alert(2)&lt;/script&gt;') in outside_the_data


def test_the_dictionaries_have_the_same_keys_and_placeholders():
    en, vi = i18n.dictionary('en'), i18n.dictionary('vi')
    assert en.keys() == vi.keys()
    assert all(i18n.placeholders(en[key]) == i18n.placeholders(vi[key]) for key in en)
    assert i18n.dictionaries() == {'en': en, 'vi': vi}
    assert i18n.dictionary('fr') is en  # any other language is the default's


def read(*path):
    with open(os.path.join(ROOT, *path), encoding='utf-8') as f:
        return f.read()


def is_key(key, strings):
    """key is a text of strings, or the base of a plural pair (key.one, key.other)."""
    return key in strings or f'{key}.other' in strings


def template_keys():
    """Every key templates/main.html names: t['...'], the rich macro, and the
    data-i18n, data-i18n-rich and data-i18n-attr attributes the script re-renders."""
    page = read('templates', 'main.html')
    keys = set(re.findall(r"""\bt\[['"]([^'"]+)['"]\]""", page))
    keys |= set(re.findall(r"""\brich\('([^']+)'\)""", page))
    keys |= set(re.findall(r'\bdata-i18n(?:-rich)?="([^"]+)"', page))
    for pairs in re.findall(r'\bdata-i18n-attr="([^"]+)"', page):
        for pair in pairs.split(';'):
            attribute, _, key = pair.partition(':')
            assert attribute.strip() and key.strip(), pairs
            keys.add(key.strip())
    return keys


def test_every_key_the_template_uses_is_in_the_dictionaries():
    # Jinja would render a missing key as nothing, and the script as the key itself.
    used = template_keys()
    assert len(used) > 50
    strings = i18n.dictionary('en')
    assert sorted(key for key in used if not is_key(key, strings)) == []


SCRIPTS = os.path.join(ROOT, 'static', 'javascript')


def script_keys():
    """The keys the page's scripts name literally: the first quoted argument
    of t(), text(), rich() and attr(), and any other string that starts with
    an area of the dictionaries ('notice.offline.title' in a notice's spec)."""
    areas = {key.split('.')[0] for key in i18n.dictionary('en')}
    keys = set()
    for name in sorted(os.listdir(SCRIPTS)):
        source = read('static', 'javascript', name)
        keys |= set(re.findall(r"""\b(?:t|text|rich)\(\s*(?:[\w.]+,\s*)?'([^'$]+)'""", source))
        keys |= set(re.findall(r"""\battr\(\s*[\w.]+,\s*'[^']+',\s*'([^'$]+)'""", source))
        keys |= {literal for literal in re.findall(r"""'([a-z][A-Za-z]*(?:\.[A-Za-z0-9_]+)+)'""", source)
                 if literal.split('.')[0] in areas}
    return keys


def test_every_key_the_scripts_use_is_in_the_dictionaries():
    used = script_keys()
    assert {'controls.speak', 'controls.cantRecord', 'notice.offline.title', 'rec.recording', 'count.words',
            'result.meaning'} <= used
    strings = i18n.dictionary('en')
    assert sorted(key for key in used if not is_key(key, strings)) == []


# context/design-system.md §5: the page shows its own text for every code the
# server answers with (client_gone never reaches a page), and for no answer.
ERROR_CODES = ['text_too_long', 'text_not_english', 'text_bad_characters', 'invalid_request', 'bad_category',
               'bad_language', 'no_audio', 'bad_audio', 'audio_too_long', 'request_entity_too_large', 'no_speech',
               'busy', 'tts_busy', 'tts_unavailable', 'tts_failed', 'scoring_failed', 'server_error',
               'timeout', 'network', 'offline', 'unknown']


@pytest.mark.parametrize('language', i18n.LANGUAGES)
def test_every_error_code_has_the_pages_own_text(language):
    strings = i18n.dictionary(language)
    assert [code for code in ERROR_CODES if not strings.get(f'error.{code}', '').strip()] == []


def test_plurals_come_in_pairs():
    # i18n.js chooses key.one or key.other with Intl.PluralRules; Vietnamese
    # only ever asks for .other, but both languages have the same keys.
    strings = i18n.dictionary('en')
    bases = {key.rsplit('.', 1)[0] for key in strings if key.endswith(('.one', '.other'))}
    assert bases, 'no plural yet'
    for base in bases:
        assert f'{base}.one' in strings and f'{base}.other' in strings, base
        assert base not in strings, base


def inter_ranges():
    """The code point ranges of the Inter @font-face rules of style.css."""
    ranges = []
    for block in re.findall(r'@font-face \{(.*?)\}', read('static', 'css', 'style.css'), re.S):
        if '"Inter"' in block:
            for part in re.search(r'unicode-range: ([^;]+);', block).group(1).split(','):
                low, _, high = part.strip()[2:].partition('-')
                ranges.append((int(low, 16), int(high or low, 16)))
    return ranges


@pytest.mark.parametrize('language', i18n.LANGUAGES)
def test_every_text_is_nfc_and_drawn_by_inter(language):
    # Precomposed Vietnamese letters (NFC) are the ones Inter's subsets have;
    # a character outside them would come from another font.
    ranges = inter_ranges()
    assert len(ranges) > 10
    for key, text in i18n.dictionary(language).items():
        assert unicodedata.normalize('NFC', text) == text, key
        missing = sorted({ch for ch in text if not any(low <= ord(ch) <= high for low, high in ranges)})
        assert not missing, (key, missing)


def test_a_text_is_cut_at_its_placeholders_for_the_template():
    assert i18n.parts('Tap {mic}, then {stop}.') == [('text', 'Tap '), ('slot', 'mic'), ('text', ', then '),
                                                     ('slot', 'stop'), ('text', '.')]
    assert i18n.parts('{a}{b}') == [('slot', 'a'), ('slot', 'b')]
    assert i18n.parts('No slot') == [('text', 'No slot')]
    assert i18n.parts('') == []


@pytest.mark.parametrize('lang', ['en', 'vi'])
def test_rich_texts_are_rendered_with_their_elements(client, lang):
    page = get_page(client, lang).get_data(as_text=True)
    strings = i18n.dictionary(lang)
    slow = f'<b data-slot="slow" data-i18n="card.slow">{strings["card.slow"]}</b>'
    before, _, after = strings['how.step1'].partition('{slow}')
    assert f'<li data-i18n-rich="how.step1">{before}{slow}{after}</li>' in page


@pytest.mark.parametrize('lang', ['en', 'vi'])
def test_the_footer_credits_ismart(client, lang):
    page = get_page(client, lang).get_data(as_text=True)
    footer = re.search(r'<footer class="footer">(.*?)</footer>', page, re.S).group(1)
    credits = i18n.dictionary(lang)['footer.credits']
    assert credits.startswith('© 2026 iSMART · ')
    assert f'<p data-i18n="footer.credits">{credits}</p>' in footer
    # Under it, the licence notice: the source code (AGPL-3.0), the original project and Tatoeba (CC BY).
    assert '<p class="footer-notice" data-i18n-rich="footer.notice">' in footer
    for href in ('https://github.com/likemoue/ai-pronunciation-trainer',
                 'https://github.com/Thiagohgl/ai-pronunciation-trainer', 'https://tatoeba.org'):
        assert f'href="{href}"' in footer
    assert 'AGPL-3.0' in footer and 'CC BY 2.0 FR' in footer


def write_pair(folder, en, vi):
    """Dictionaries for English and Vietnamese in folder (created)."""
    folder.mkdir()
    for language, strings in (('en', en), ('vi', vi)):
        (folder / f'{language}.json').write_text(json.dumps(strings, ensure_ascii=False), encoding='utf-8')
    return str(folder)


def test_a_pair_that_agrees_is_loaded(tmp_path):
    folder = write_pair(tmp_path / 'i18n', {'words': '{count} of {total} words'}, {'words': '{count}/{total} từ'})
    assert i18n.load(folder) == {'en': {'words': '{count} of {total} words'}, 'vi': {'words': '{count}/{total} từ'}}
    assert i18n.placeholders('{count} of {total}, {count}') == {'count', 'total'}


@pytest.mark.parametrize('en,vi,problem', [
    ({'a': 'A', 'b': 'B'}, {'a': 'Á'}, 'different keys'),
    ({'a': 'A'}, {'a': 'Á', 'b': 'B'}, 'different keys'),
    ({'a': 'Hello, {name}'}, {'a': 'Xin chào'}, 'different placeholders'),
    ({'a': '{count} words'}, {'a': '{n} từ'}, 'different placeholders'),
    ({'a': {'nested': 'A'}}, {'a': 'Á'}, 'not a flat object of strings'),
    ({'a': 3}, {'a': 'Á'}, 'not a flat object of strings'),
    (['a'], ['a'], 'not a flat object of strings'),
])
def test_dictionaries_that_disagree_are_refused(tmp_path, en, vi, problem):
    with pytest.raises(i18n.DictionaryError, match=problem):
        i18n.load(write_pair(tmp_path / 'i18n', en, vi))


def test_a_key_given_twice_and_broken_json_are_refused(tmp_path):
    folder = write_pair(tmp_path / 'i18n', {'a': 'A'}, {'a': 'Á'})
    with open(os.path.join(folder, 'vi.json'), 'w', encoding='utf-8') as f:
        f.write('{"a": "Á", "a": "B"}')
    with pytest.raises(i18n.DictionaryError, match='a given twice'):
        i18n.load(folder)
    with open(os.path.join(folder, 'vi.json'), 'w', encoding='utf-8') as f:
        f.write('{"a": "Á",}')
    with pytest.raises(i18n.DictionaryError, match='vi.json'):
        i18n.load(folder)


def test_a_byte_order_mark_is_allowed(tmp_path):
    folder = write_pair(tmp_path / 'i18n', {'a': 'A'}, {'a': 'Á'})
    with open(os.path.join(folder, 'vi.json'), 'wb') as f:
        f.write(b'\xef\xbb\xbf' + '{"a": "Á"}'.encode('utf-8'))
    assert i18n.load(folder)['vi'] == {'a': 'Á'}


def test_the_module_does_not_import_with_dictionaries_that_disagree(tmp_path):
    # The check runs at import: a worker whose dictionaries disagree does not start.
    shutil.copy(i18n.__file__, tmp_path / 'i18n.py')
    write_pair(tmp_path / 'i18n', {'a': 'Hello, {name}'}, {'a': 'Xin chào'})
    spec = importlib.util.spec_from_file_location('i18n_with_a_bad_pair', tmp_path / 'i18n.py')
    with pytest.raises(ValueError, match='different placeholders'):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
