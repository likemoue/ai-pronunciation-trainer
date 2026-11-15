"""Static files: versioned by content, cached for a year only under their
current version, and nothing loaded from another site."""
import os
import re

import pytest

import webApp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMMUTABLE = 'public, max-age=31536000, immutable'


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as f:
        return f.read()


def test_the_asset_version_is_a_hash_of_the_stylesheet_and_script():
    assert re.fullmatch(r'[0-9a-f]{12}', webApp.ASSET_VERSION)
    assert webApp._asset_version() == webApp.ASSET_VERSION  # the same files give the same token


def test_the_page_asks_for_the_current_versions(client):
    page = client.get('/').get_data(as_text=True)
    assert f'/static/css/style.css?v={webApp.ASSET_VERSION}' in page
    assert f'/static/javascript/app.js?v={webApp.ASSET_VERSION}' in page
    assert '/static/fonts/inter-latin.woff2' in page  # preloaded


@pytest.mark.parametrize('path', ['/static/css/style.css', '/static/javascript/app.js'])
def test_a_current_asset_is_immutable_and_any_other_is_checked(client, path):
    assert client.get(f'{path}?v={webApp.ASSET_VERSION}').headers['Cache-Control'] == IMMUTABLE
    # An old page (or a colour that has not switched yet) asks for another
    # version: the answer is today's file, which must not be cached under that name.
    assert client.get(f'{path}?v=0123456789ab').headers['Cache-Control'] == 'no-cache'
    assert client.get(path).headers['Cache-Control'] == 'no-cache'


def test_fonts_are_immutable(client):
    response = client.get('/static/fonts/inter-latin.woff2')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == IMMUTABLE
    assert response.mimetype == 'font/woff2'
    assert response.data[:4] == b'wOF2'


def test_a_missing_static_file_is_not_cached(client):
    response = client.get(f'/static/fonts/missing.woff2?v={webApp.ASSET_VERSION}')
    assert response.status_code == 404
    assert response.headers['Cache-Control'] != IMMUTABLE


def test_the_page_is_checked_and_the_api_is_never_stored(client, fake_voice):
    assert client.get('/').headers['Cache-Control'] == 'no-cache'
    for path in ('/healthz', '/readyz', '/version'):
        assert client.get(path).headers['Cache-Control'] == 'no-store', path
    response = client.post('/getSample', json={'category': 1, 'language': 'en'})
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    response = client.post('/getAudioFromText', json={'value': 'Hello there', 'language': 'en'})
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'


def test_nothing_is_loaded_from_another_site():
    csp = webApp.CONTENT_SECURITY_POLICY
    assert "style-src 'self';" in csp and "font-src 'self';" in csp
    assert 'googleapis' not in csp and 'gstatic' not in csp
    page = read('templates/main.html')
    for tag in re.findall(r'<(?:link|script|img|audio|source)\b[^>]*>', page):
        assert not re.search(r'(?:href|src)="https?://', tag), tag
    assert 'url(http' not in read('static/css/style.css')


def test_every_font_the_stylesheet_names_is_served_with_its_licence():
    css = read('static/css/style.css')
    fonts = re.findall(r'url\("\.\./fonts/([^"]+)"\)', css)
    assert len(fonts) == 5
    for name in fonts:
        assert os.path.isfile(os.path.join(ROOT, 'static', 'fonts', name)), name
    for licence in ('OFL-Inter.txt', 'OFL-NotoSans.txt'):
        assert 'SIL Open Font License' in read(f'static/fonts/{licence}')


def test_the_page_downloads_no_sound_files():
    # The result chime is synthesised in the browser (app.js).
    assert not [name for _, _, names in os.walk(os.path.join(ROOT, 'static')) for name in names
                if name.endswith(('.wav', '.mp3', '.ogg'))]


def test_every_ipa_symbol_of_the_bank_has_a_served_font():
    # The IPA font's subsets must cover every symbol the page shows (θ is Greek).
    import pandas as pd
    import RuleBasedModels
    import validation
    css = read('static/css/style.css')
    ranges = []
    for block in re.findall(r'@font-face \{(.*?)\}', css, re.S):
        if '"Noto Sans"' in block:
            for part in re.search(r'unicode-range: ([^;]+);', block).group(1).split(','):
                low, _, high = part.strip()[2:].partition('-')
                ranges.append((int(low, 16), int(high or low, 16)))
    converter = RuleBasedModels.EngPhonemConverter()
    sentences = pd.read_csv('databases/data_en.csv', delimiter=';')['sentence'].astype(str).tolist()
    symbols = {ch for s in sentences[:3000] for ch in converter.convertToPhonem(validation.normalize_text(s))}
    missing = sorted(ch for ch in symbols if not ch.isspace() and not any(lo <= ord(ch) <= hi for lo, hi in ranges))
    assert not missing, missing
