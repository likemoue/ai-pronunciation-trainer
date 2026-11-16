# Configure logging before importing the model code: epitran calls
# logging.basicConfig(level=CRITICAL) on import, which would otherwise hide
# every warning and error the app logs. Libraries that log through the root
# logger log errors only; see logging_setup.
import logging_setup
logging_setup.configure()

import hashlib  # noqa: E402
import mimetypes  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import select  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
import webbrowser  # noqa: E402

from flask import Flask, render_template, request, g, abort, url_for  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

import audioPreprocessing  # noqa: E402
import i18n  # noqa: E402
import lambdaGetSample  # noqa: E402
import lambdaSpeechToScore  # noqa: E402
import language_registry  # noqa: E402
import piperTTS  # noqa: E402
import readiness  # noqa: E402
import validation  # noqa: E402

logger = logging_setup.get_logger(__name__)
_STARTED_AT = time.time()
# The slim image has no /etc/mime.types, and Python's own table may not know
# the font format: without this the fonts go out as application/octet-stream.
mimetypes.add_type('font/woff2', '.woff2')

app = Flask(__name__)
# Largest request body accepted. A 30 s browser recording is well under 1 MB,
# even base64-encoded; Flask answers 413 before reading anything bigger.
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_REQUEST_BYTES', str(4 * 1024 * 1024)))

rootPath = ''

# The stylesheets and scripts: every file in these folders of static/. The page
# asks for each with its version (asset_url), so a new script is versioned and
# cached like the others without a change here.
_ASSET_FOLDERS = ('css', 'javascript')

# The page loads its own scripts, stylesheets and fonts, and the Cloudflare Web
# Analytics beacon that the CDN injects.
CONTENT_SECURITY_POLICY = '; '.join([
    "default-src 'self'",
    "script-src 'self' https://static.cloudflareinsights.com",
    "style-src 'self'",
    "font-src 'self'",
    "img-src 'self' data:",
    "media-src 'self' blob: data:",
    "connect-src 'self' https://cloudflareinsights.com",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
])

SECURITY_HEADERS = {
    'Content-Security-Policy': CONTENT_SECURITY_POLICY,
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'microphone=(self), camera=(), geolocation=()',
}


def _asset_files(static_folder=None) -> tuple:
    """The stylesheets and scripts, by the path the page asks for under
    /static/ ('javascript/app.js'), sorted: the same files give the same
    list on any machine and in any folder."""
    static_folder = static_folder or app.static_folder
    paths = []
    for folder in _ASSET_FOLDERS:
        for parent, _, names in os.walk(os.path.join(static_folder, folder)):
            paths += [os.path.relpath(os.path.join(parent, name), static_folder).replace(os.sep, '/')
                      for name in names]
    return tuple(sorted(paths))


def _asset_version(static_folder=None) -> str:
    """Cache-busting token for the stylesheets and scripts: a hash of their
    names and content, so the same files give the same token in every build
    and colour, and a change to any of them, or a new one, gives a new one."""
    static_folder = static_folder or app.static_folder
    digest = hashlib.sha256()
    for path in _asset_files(static_folder):
        with open(os.path.join(static_folder, path), 'rb') as f:
            content = f.read()
        digest.update(f'{path} {len(content)}:'.encode())
        digest.update(content)
    return digest.hexdigest()[:12]


_STATIC_ASSETS = _asset_files()
ASSET_VERSION = _asset_version()
# The page asks for /static/<asset>?v=ASSET_VERSION, and for the fonts, whose
# names change with their content. Browsers and Cloudflare may keep those for a
# year. Anything else under /static (an asset with an old or no version, during
# a deploy or from a cached page) must be checked with the server each time.
_IMMUTABLE = 'public, max-age=31536000, immutable'


def _cache_control(response):
    endpoint = request.endpoint
    if endpoint == 'static':
        filename = (request.view_args or {}).get('filename', '')
        versioned = filename in _STATIC_ASSETS and request.args.get('v') == ASSET_VERSION
        if response.status_code in (200, 304) and (versioned or filename.startswith('fonts/')):
            return _IMMUTABLE
        return 'no-cache'
    if endpoint == 'main':
        return 'no-cache'  # the page names the current asset versions
    # The API answers with a learner's text and scores: never stored by a cache.
    return response.headers.get('Cache-Control') or 'no-store'


def _error(message, status, code='error'):
    return {"error": message, "code": code}, status


def _busy(message, retry_after, code='busy'):
    """503 with Retry-After: the client keeps what it sent and tries again."""
    body, status = _error(message, 503, code)
    body['retry_after'] = retry_after
    return body, status, {'Retry-After': str(retry_after)}


def _client_gone_check():
    """A function that tells whether the client of this request has closed its
    connection, or None outside gunicorn. Caddy closes its connection to the
    app when the browser gives up on a request (the learner closed the popup,
    or the page's own timeout), so a recording that waited can be skipped."""
    sock = request.environ.get('gunicorn.socket')
    if sock is None or not hasattr(select, 'poll'):
        return None

    def gone() -> bool:
        try:
            poller = select.poll()
            poller.register(sock, select.POLLIN)
            if not poller.poll(0):
                return False  # nothing to read: the connection is open and idle
            # Readable with nothing to read means the other side closed it.
            return sock.recv(1, socket.MSG_PEEK) == b''
        except OSError:
            return True
    return gone


# A Ray ID is 16 hex digits and the code of the Cloudflare data centre.
_RAY_ID = re.compile(r'[0-9a-f]{16}-[A-Z]{3,4}')


@app.before_request
def _assign_request_id():
    # Cloudflare's Ray ID is what users see on error pages, so reuse it. The
    # header is only trusted when it looks like one: port 3000 is reachable
    # from the LAN without Cloudflare in front, so the value is not proof that
    # the request came through Cloudflare.
    ray_id = request.headers.get('CF-Ray', '')
    g.request_id = ray_id if _RAY_ID.fullmatch(ray_id) else uuid.uuid4().hex[:16]


@app.after_request
def _add_headers(response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    response.headers['X-Request-ID'] = g.get('request_id', '')
    response.headers['Cache-Control'] = _cache_control(response)
    return response


@app.errorhandler(validation.ValidationError)
def _handle_validation_error(e):
    return _error(str(e), e.status, e.code)


@app.errorhandler(HTTPException)
def _handle_http_error(e):
    messages = {413: 'The request is too large.',
                415: 'Requests must be sent as JSON.'}
    body, status = _error(messages.get(e.code, e.description), e.code, e.name.lower().replace(' ', '_'))
    # Keep headers such as Allow on a 405; the body is JSON, not HTML.
    headers = [(name, value) for name, value in e.get_headers() if name.lower() != 'content-type']
    return body, status, headers


@app.errorhandler(Exception)
def _handle_unexpected_error(e):
    logger.exception('Unhandled error')
    return _error('Something went wrong on the server.', 500, 'server_error')


def _json_body() -> dict:
    """The request body as a dict. Only application/json is accepted: a
    cross-site HTML form cannot send it without a CORS preflight."""
    if not request.is_json:
        abort(415)
    try:
        data = request.get_data(cache=True)  # get_json below parses these cached bytes
    except HTTPException:
        raise  # 413 for a Content-Length over the limit, 400 for a client that went away
    except Exception:  # noqa: BLE001 - e.g. gunicorn's errors for malformed chunked encoding
        raise validation.ValidationError('The request body could not be read.') from None
    # A chunked body has no Content-Length, so reading stops at the limit
    # instead of refusing it; and a body shorter than its Content-Length was
    # cut off by the client. Neither may be parsed as if it were complete.
    if request.content_length is None and len(data) >= app.config['MAX_CONTENT_LENGTH']:
        abort(413)
    if request.content_length is not None and len(data) < request.content_length:
        raise validation.ValidationError('The request body could not be read.')
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # deeply nested JSON; silent=True only covers ValueError
        body = None
    if not isinstance(body, dict):
        raise validation.ValidationError('The request body must be a JSON object.')
    return body


def _request_language(body) -> str:
    language = body.get('language') or language_registry.ENABLED_LANGUAGES[0]
    if not isinstance(language, str) or not language_registry.is_enabled(language):
        raise validation.ValidationError('This language is not available on this server.',
                                         code='bad_language')
    return language


@app.template_global()
def asset_url(path: str) -> str:
    """The URL of a stylesheet or script with its version, for the template:
    asset_url('javascript/app.js') is /static/javascript/app.js?v=<ASSET_VERSION>,
    which browsers and Cloudflare keep for a year (_cache_control). A path that
    is not one of them (a typo, a file the image lacks) fails the page."""
    if path not in _STATIC_ASSETS:
        raise ValueError(f'{path!r} is not a file of static/{" or static/".join(_ASSET_FOLDERS)}')
    return url_for('static', filename=path, v=ASSET_VERSION)


# A dictionary text cut at its placeholders, for the template's texts with
# elements in them (the `rich` macro of templates/main.html).
app.add_template_global(i18n.parts, 'i18n_parts')


@app.route(rootPath+'/')
def main():
    # In the learner's language, from the cookie the page sets when they
    # choose one, so a Vietnamese page comes without English first; the
    # script gets both dictionaries and switches language in place.
    lang = i18n.choose(request.cookies.get('lang'))
    response = app.make_response(render_template('main.html', lang=lang, t=i18n.dictionary(lang),
                                                 dictionaries=i18n.dictionaries()))
    response.vary.add('Cookie')  # one URL, two pages
    return response


@app.route(rootPath+'/getAudioFromText', methods=['POST'])
def getAudioFromText():
    body = _json_body()
    text = validation.speech_text(body.get('value'))
    language = _request_language(body)

    if not (piperTTS.is_available() and language in piperTTS.VOICE_CONFIGS):
        # Permanent: the browser switches to its own speechSynthesis voice.
        return _error('Server-side TTS is not available.', 503, 'tts_unavailable')
    try:
        wav_b64 = piperTTS.generate_wav_base64(text, language=language)
    except piperTTS.BusyError:
        # Temporary: the browser reads this text with its own voice.
        return _busy('The server is busy reading other texts aloud.', 2, 'tts_busy')
    except piperTTS.TextTooLongError as e:
        logger.warning('TTS text refused: %s', e)
        return _error('This text is too long to read aloud.', 400, 'text_too_long')
    except Exception:
        logger.exception('TTS failed')
        # Temporary: the browser falls back to its own voice for this text only.
        return _error('Could not generate audio.', 503, 'tts_failed')
    return {"wavBase64": wav_b64}


@app.route(rootPath+'/tts/<language>/<key>.mp3')
def bankSentenceAudio(language, key):
    """The reference voice reading a bank sentence, as MP3. The URL names the
    sentence and the voice (lambdaGetSample.audio_key), so the file never
    changes: browsers and Cloudflare keep it, and most learners who get the
    same sentence never reach the server. Other texts go through
    /getAudioFromText."""
    if not language_registry.is_enabled(language):
        abort(404)
    sentence = lambdaGetSample.sentence_for_audio_key(language, key)
    if sentence is None:
        abort(404)
    if not (piperTTS.is_available() and language in piperTTS.VOICE_CONFIGS):
        return _error('Server-side TTS is not available.', 503, 'tts_unavailable')
    try:
        mp3 = piperTTS.generate_mp3(sentence, language=language)
    except piperTTS.BusyError:
        return _busy('The server is busy reading other texts aloud.', 2, 'tts_busy')
    except Exception:
        logger.exception('TTS failed')
        return _error('Could not generate audio.', 503, 'tts_failed')
    response = app.response_class(mp3, mimetype='audio/mpeg')
    response.headers['Cache-Control'] = _IMMUTABLE
    return response


@app.route(rootPath+'/getSample', methods=['POST'])
def getNext():
    body = _json_body()
    language = _request_language(body)
    return lambdaGetSample.sample(body.get('category'), language)


@app.route(rootPath+'/getCustomSample', methods=['POST'])
def getCustomSample():
    body = _json_body()
    language = _request_language(body)
    return lambdaGetSample.custom_sample(body.get('text'), language)


@app.route(rootPath+'/GetAccuracyFromRecordedAudio', methods=['POST'])
def GetAccuracyFromRecordedAudio():
    body = _json_body()
    language = _request_language(body)
    title = validation.practice_text(body.get('title'),
                                     empty_message='There is no sentence to compare with.')
    audio = validation.audio_bytes(body.get('base64Audio'))

    try:
        return lambdaSpeechToScore.score(title, audio, language, client_gone=_client_gone_check())
    except lambdaSpeechToScore.ServerBusyError as e:
        return _busy('The server is busy. Your recording will be sent again in a moment.', e.retry_after)
    except lambdaSpeechToScore.ClientGoneError:
        # Nobody reads this answer; 499 marks it in the access log, as nginx does.
        return _error('The client closed the connection.', 499, 'client_gone')
    except lambdaSpeechToScore.NoSpeechError:
        return _error("We couldn't recognise any speech.", 422, 'no_speech')
    except audioPreprocessing.AudioTooLongError:
        return _error('The recording is too long. Please keep it under 30 seconds.', 413, 'audio_too_long')
    except audioPreprocessing.AudioDecodeError as e:
        logger.warning('Unreadable recording: %s', e)
        return _error('The recording could not be read. Please try again.', 400, 'bad_audio')
    except Exception:
        logger.exception('Scoring failed')
        return _error('Could not process the recording.', 500, 'scoring_failed')


_worker_ready = False


@app.route(rootPath+'/healthz')
def healthz():
    """Liveness: the process answers HTTP. Never touches the models."""
    return {'status': 'ok', 'uptime_s': round(time.time() - _STARTED_AT)}


@app.route(rootPath+'/readyz')
def readyz():
    """Readiness: every worker has scored its warm-up sentence (the same test
    as the Docker HEALTHCHECK)."""
    expected = readiness.expected_workers()
    ready = readiness.ready_workers()
    body = {'ready_workers': ready, 'expected_workers': expected, 'this_worker_ready': _worker_ready}
    return body, (200 if ready >= expected else 503)


@app.route(rootPath+'/version')
def version():
    return {'git_sha': os.environ.get('GIT_SHA', 'unknown'),
            'git_date': os.environ.get('GIT_DATE', 'unknown')}


def _mark_ready():
    """Tell the container health check that this worker finished its warm-up."""
    global _worker_ready
    _worker_ready = True
    try:
        readiness.mark_ready()
    except OSError as e:
        logger.warning('Could not write the readiness marker: %s', e)


def _warm_up_models():
    """Load models in the background so the first user does not wait for them.

    The worker is marked ready once every preloaded language has scored its
    warm-up sentence. With nothing to preload (PRELOAD_LANGUAGES=''), it is
    ready at once and the models load on the first request.
    """
    languages = [lang.strip() for lang in os.environ.get('PRELOAD_LANGUAGES', 'en').split(',') if lang.strip()]
    all_ok = True
    for lang in languages:
        if not language_registry.is_enabled(lang):
            logger.warning('PRELOAD_LANGUAGES lists "%s", which is not in ENABLED_LANGUAGES; '
                           'it is not warmed up.', lang)
            continue
        started = time.perf_counter()
        try:
            if piperTTS.is_available() and lang in piperTTS.VOICE_CONFIGS:
                piperTTS.warm_up(lang)
            ok = lambdaSpeechToScore.warm_up(lang)
        except Exception:
            logger.exception('Warm-up failed for %s', lang)
            ok = False
        all_ok = all_ok and ok
        fields = {'event': 'warmup', 'language': lang, 'ok': ok,
                  'seconds': round(time.perf_counter() - started, 1)}
        if ok:
            logger.info('Warm-up done for %s', lang, extra={'fields': fields})
        else:
            logger.error('Warm-up FAILED for %s', lang, extra={'fields': fields})
    if all_ok:
        _mark_ready()


_warm_up_lock = threading.Lock()
_warm_up_started = False


def start_warm_up():
    """Load the models in a background thread, once per process. gunicorn calls
    this from the post_worker_init hook in gunicorn.conf.py."""
    global _warm_up_started
    with _warm_up_lock:
        if _warm_up_started:
            return
        _warm_up_started = True
    # ONNX Runtime is imported while this process still has one thread: its
    # start-up messages go through stderr, which piperTTS borrows for that.
    piperTTS.is_available()
    threading.Thread(target=_warm_up_models, daemon=True, name='warm-up').start()


if __name__ == "__main__":
    # One process serves everything, so /readyz waits for one warm-up, and
    # markers left by an earlier run must not count.
    os.environ.setdefault('WEB_CONCURRENCY', '1')
    readiness.reset()
    start_warm_up()
    if os.environ.get('OPEN_BROWSER', '1') == '1':
        webbrowser.open_new('http://127.0.0.1:3000/')
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', '3000')))
