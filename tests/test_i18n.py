"""The interface language: the page in English or Vietnamese from the `lang`
cookie (webApp.main), and the dictionaries (i18n.py, i18n/*.json) that the
template and the page's script read."""
import html.parser
import importlib.util
import json
import os
import re
import shutil

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
    sneaky = {'page.title': 'AI Pronunciation Trainer',
              'page.description': '</script><script>alert(1)</script><!-- & \'"'}
    monkeypatch.setattr(i18n, '_DICTIONARIES', {'en': sneaky, 'vi': sneaky})
    scripts = Scripts(get_page(client).get_data(as_text=True)).scripts
    assert [script['attrs'].get('type') for script in scripts if 'src' not in script['attrs']] == ['application/json']
    data = next(script for script in scripts if script['attrs'].get('id') == 'i18nData')
    assert json.loads(data['text']) == {'en': sneaky, 'vi': sneaky}


def test_the_dictionaries_have_the_same_keys_and_placeholders():
    en, vi = i18n.dictionary('en'), i18n.dictionary('vi')
    assert en.keys() == vi.keys()
    assert all(i18n.placeholders(en[key]) == i18n.placeholders(vi[key]) for key in en)
    assert i18n.dictionaries() == {'en': en, 'vi': vi}
    assert i18n.dictionary('fr') is en  # any other language is the default's


def test_every_key_the_template_uses_is_in_the_dictionaries():
    # Jinja would render a missing key as nothing.
    with open(os.path.join(ROOT, 'templates', 'main.html'), encoding='utf-8') as f:
        used = set(re.findall(r"""\bt\[['"]([^'"]+)['"]\]""", f.read()))
    assert used and used <= i18n.dictionary('en').keys()


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
