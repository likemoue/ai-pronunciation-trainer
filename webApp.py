from flask import Flask, render_template, request, g, abort
from werkzeug.exceptions import HTTPException
import webbrowser
import os
import threading
import json
import uuid

import lambdaTTS
import lambdaSpeechToScore
import lambdaGetSample
import language_registry
import piperTTS
import audioPreprocessing
import validation

app = Flask(__name__)
# Largest request body accepted. A 30 s browser recording is well under 1 MB,
# even base64-encoded; Flask answers 413 before reading anything bigger.
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_REQUEST_BYTES', str(4 * 1024 * 1024)))

rootPath = ''

_STATIC_ASSETS = ('static/css/style.css', 'static/javascript/app.js')

# The page loads its own script and stylesheet, Google Fonts, and the
# Cloudflare Web Analytics beacon that the CDN injects.
CONTENT_SECURITY_POLICY = '; '.join([
    "default-src 'self'",
    "script-src 'self' https://static.cloudflareinsights.com",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
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


def _asset_version() -> str:
    """Cache-busting token that changes whenever the CSS/JS bundle changes."""
    base = os.path.dirname(os.path.abspath(__file__))
    mtimes = [os.path.getmtime(os.path.join(base, path))
              for path in _STATIC_ASSETS if os.path.exists(os.path.join(base, path))]
    return str(int(max(mtimes))) if mtimes else '1'


ASSET_VERSION = _asset_version()


def _error(message, status, code='error'):
    return {"error": message, "code": code}, status


@app.before_request
def _assign_request_id():
    # Cloudflare's Ray ID is what users see on error pages, so reuse it.
    g.request_id = request.headers.get('CF-Ray') or uuid.uuid4().hex[:16]


@app.after_request
def _add_headers(response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    response.headers['X-Request-ID'] = g.get('request_id', '')
    return response


@app.errorhandler(validation.ValidationError)
def _handle_validation_error(e):
    return _error(str(e), e.status, e.code)


@app.errorhandler(HTTPException)
def _handle_http_error(e):
    messages = {413: 'The request is too large.',
                415: 'Requests must be sent as JSON.'}
    return _error(messages.get(e.code, e.description), e.code, e.name.lower().replace(' ', '_'))


@app.errorhandler(Exception)
def _handle_unexpected_error(e):
    app.logger.exception('Unhandled error (request %s)', g.get('request_id', '-'))
    return _error('Something went wrong on the server.', 500, 'server_error')


def _json_body() -> dict:
    """The request body as a dict. Only application/json is accepted: a
    cross-site HTML form cannot send it without a CORS preflight."""
    if not request.is_json:
        abort(415)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise validation.ValidationError('The request body must be a JSON object.')
    return body


def _request_language(body) -> str:
    language = body.get('language') or language_registry.ENABLED_LANGUAGES[0]
    if not isinstance(language, str) or not language_registry.is_enabled(language):
        raise validation.ValidationError('This language is not available on this server.',
                                         code='bad_language')
    return language


@app.route(rootPath+'/')
def main():
    return render_template('main.html', asset_version=ASSET_VERSION)


@app.route(rootPath+'/getAudioFromText', methods=['POST'])
def getAudioFromText():
    body = _json_body()
    text = validation.practice_text(body.get('value'), empty_message='No text to read.')
    language = _request_language(body)

    # Prefer Piper on any OS where it is installed; it is fast and natural-sounding.
    if piperTTS.is_available() and language in piperTTS.VOICE_CONFIGS:
        try:
            wav_b64 = piperTTS.generate_wav_base64(text, language=language)
        except Exception:
            app.logger.exception('TTS failed (request %s)', g.request_id)
            # Temporary: the browser falls back to its own voice for this text only.
            return _error('Could not generate audio.', 503, 'tts_failed')
        return {"wavBase64": wav_b64}
    if language == 'de':
        # The Silero fallback only ships a German voice.
        event = {'body': json.dumps({'value': text})}
        result = lambdaTTS.lambda_handler(event, [])
        return json.loads(result['body'])
    # Permanent: the browser switches to its own speechSynthesis voice.
    return _error('Server-side TTS is not available.', 503, 'tts_unavailable')


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
        return lambdaSpeechToScore.score(title, audio, language)
    except lambdaSpeechToScore.NoSpeechError:
        return _error("We couldn't recognise any speech.", 422, 'no_speech')
    except audioPreprocessing.AudioTooLongError:
        return _error('The recording is too long. Please keep it under 30 seconds.', 413, 'audio_too_long')
    except audioPreprocessing.AudioDecodeError as e:
        app.logger.warning('Unreadable recording (request %s): %s', g.request_id, e)
        return _error('The recording could not be read. Please try again.', 400, 'bad_audio')
    except Exception:
        app.logger.exception('Scoring failed (request %s)', g.request_id)
        return _error('Could not process the recording.', 500, 'scoring_failed')


READY_DIR = os.environ.get('READY_DIR', '/tmp/aipt-ready')


def _mark_ready():
    """Tell the container health check that this worker finished its warm-up."""
    try:
        os.makedirs(READY_DIR, exist_ok=True)
        with open(os.path.join(READY_DIR, str(os.getpid())), 'w') as marker:
            marker.write('ready\n')
    except OSError as e:
        print(f'Could not write the readiness marker: {e}')


def _warm_up_models():
    """Load models in the background so the first user does not wait for them."""
    languages = [lang.strip() for lang in os.environ.get('PRELOAD_LANGUAGES', 'en').split(',') if lang.strip()]
    if not languages:
        return
    all_ok = True
    for lang in languages:
        if not language_registry.is_enabled(lang):
            continue
        try:
            if piperTTS.is_available() and lang in piperTTS.VOICE_CONFIGS:
                piperTTS.warm_up(lang)
            ok = lambdaSpeechToScore.warm_up(lang)
        except Exception as e:
            print(f'Warm-up failed for "{lang}": {e!r}')
            ok = False
        all_ok = all_ok and ok
        print(f'Warm-up {"done" if ok else "FAILED"} for "{lang}"')
    if all_ok:
        _mark_ready()


# Start loading models as soon as the app is imported. This covers both
# `python webApp.py` and each gunicorn worker (which imports the app itself).
threading.Thread(target=_warm_up_models, daemon=True).start()


if __name__ == "__main__":
    if os.environ.get('OPEN_BROWSER', '1') == '1':
        webbrowser.open_new('http://127.0.0.1:3000/')
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', '3000')))
