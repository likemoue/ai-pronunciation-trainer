"""The stylesheets and scripts are every file under static/css and
static/javascript (webApp._STATIC_ASSETS): one version for all of them, a year
in caches under that version only, and the page links each through asset_url,
so a new script needs no change to webApp.py. (The font and IPA checks are in
test_static.py.)"""
import html.parser
import os
import re
import shutil

import pytest

import webApp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMMUTABLE = 'public, max-age=31536000, immutable'
SCRIPT = b"'use strict';\n"


class Links(html.parser.HTMLParser):
    """The stylesheets and scripts a page links."""

    def __init__(self, page):
        super().__init__()
        self.urls = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and 'src' in attrs:
            self.urls.append(attrs['src'])
        elif tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.urls.append(attrs['href'])


@pytest.fixture
def static_copy(tmp_path):
    """A copy of the stylesheet and script folders, to which a test can add files.
    (The image's /app is read-only for the tests.)"""
    for folder in webApp._ASSET_FOLDERS:
        shutil.copytree(os.path.join(webApp.app.static_folder, folder), tmp_path / folder)
    return tmp_path


def test_the_assets_are_the_stylesheets_and_scripts():
    assets = webApp._STATIC_ASSETS
    assert {'css/style.css', 'javascript/app.js'} <= set(assets)
    assert list(assets) == sorted(assets)
    for path in assets:
        assert path.split('/')[0] in webApp._ASSET_FOLDERS and '\\' not in path, path
        assert os.path.isfile(os.path.join(webApp.app.static_folder, path)), path


def test_the_same_files_give_the_same_version_in_any_folder(static_copy):
    # Another checkout, build or colour has its files elsewhere: the same token.
    assert webApp._asset_files(str(static_copy)) == webApp._STATIC_ASSETS
    assert webApp._asset_version(str(static_copy)) == webApp.ASSET_VERSION


def test_a_new_script_changes_the_version(static_copy):
    scripts = static_copy / 'javascript'
    (scripts / 'sheet.js').write_bytes(SCRIPT)
    assert 'javascript/sheet.js' in webApp._asset_files(str(static_copy))
    with_sheet = webApp._asset_version(str(static_copy))
    assert re.fullmatch(r'[0-9a-f]{12}', with_sheet) and with_sheet != webApp.ASSET_VERSION
    # Names count, not only content: an empty script changes it, and so does renaming it.
    (scripts / 'empty.js').write_bytes(b'')
    with_empty = webApp._asset_version(str(static_copy))
    assert with_empty != with_sheet
    (scripts / 'empty.js').rename(scripts / 'blank.js')
    assert webApp._asset_version(str(static_copy)) != with_empty
    (scripts / 'parts').mkdir()
    (scripts / 'parts' / 'tour.js').write_bytes(SCRIPT)
    assert 'javascript/parts/tour.js' in webApp._asset_files(str(static_copy))


def test_a_new_script_is_served_and_cached_like_app_js(static_copy, monkeypatch, client):
    # The app as it starts with one more script, which nothing in webApp.py names.
    (static_copy / 'javascript' / 'sheet.js').write_bytes(SCRIPT)
    monkeypatch.setattr(webApp.app, 'static_folder', str(static_copy))
    monkeypatch.setattr(webApp, '_STATIC_ASSETS', webApp._asset_files())
    monkeypatch.setattr(webApp, 'ASSET_VERSION', webApp._asset_version())
    with webApp.app.test_request_context():
        url = webApp.asset_url('javascript/sheet.js')
    assert url == f'/static/javascript/sheet.js?v={webApp.ASSET_VERSION}'
    response = client.get(url)
    assert response.status_code == 200 and response.data == SCRIPT
    assert response.headers['Cache-Control'] == IMMUTABLE
    assert client.get('/static/javascript/sheet.js?v=0123456789ab').headers['Cache-Control'] == 'no-cache'
    assert client.get('/static/javascript/sheet.js').headers['Cache-Control'] == 'no-cache'


@pytest.mark.parametrize('path', webApp._STATIC_ASSETS)
def test_every_asset_is_immutable_under_the_current_version_only(client, path):
    assert client.get(f'/static/{path}?v={webApp.ASSET_VERSION}').headers['Cache-Control'] == IMMUTABLE
    # A page from before a deploy asks for another version: today's file, not to be kept under that name.
    assert client.get(f'/static/{path}?v=0123456789ab').headers['Cache-Control'] == 'no-cache'
    assert client.get(f'/static/{path}').headers['Cache-Control'] == 'no-cache'


def test_asset_url_refuses_anything_but_a_stylesheet_or_script():
    with webApp.app.test_request_context():
        assert webApp.asset_url('css/style.css') == f'/static/css/style.css?v={webApp.ASSET_VERSION}'
        for path in ('javascript/missing.js', 'fonts/inter-latin.woff2', '/static/css/style.css',
                     'css/../css/style.css', 'css'):
            with pytest.raises(ValueError):
                webApp.asset_url(path)


def test_the_page_links_its_stylesheets_and_scripts_through_asset_url(client):
    with open(os.path.join(ROOT, 'templates', 'main.html'), encoding='utf-8') as f:
        template = f.read()
    tags = re.findall(r'<link\b[^>]*\brel="stylesheet"[^>]*>|<script\b[^>]*\bsrc=[^>]*>', template)
    through_asset_url = re.compile(r'\b(?:href|src)="\{\{ asset_url\(' + "'[^']+'" + r'\) \}\}"')
    assert tags and all(through_asset_url.search(tag) for tag in tags), tags
    assert '?v=' not in template  # versions come from asset_url only
    urls = Links(client.get('/').get_data(as_text=True)).urls
    expected = {f'/static/{path}?v={webApp.ASSET_VERSION}' for path in ('css/style.css', 'javascript/app.js')}
    assert expected <= set(urls)
    for url in urls:
        match = re.fullmatch(r'/static/(.+)\?v=([0-9a-f]{12})', url)
        assert match and match.group(1) in webApp._STATIC_ASSETS and match.group(2) == webApp.ASSET_VERSION, url
