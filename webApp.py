from flask import Flask, render_template, request
import webbrowser
import os
import threading
from flask_cors import CORS
import json

import lambdaTTS
import lambdaSpeechToScore
import lambdaGetSample
import language_registry
import piperTTS

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = '*'

rootPath = ''

_STATIC_ASSETS = ('static/css/style.css', 'static/javascript/app.js')


def _asset_version() -> str:
    """Cache-busting token that changes whenever the CSS/JS bundle changes."""
    base = os.path.dirname(os.path.abspath(__file__))
    mtimes = [os.path.getmtime(os.path.join(base, path))
              for path in _STATIC_ASSETS if os.path.exists(os.path.join(base, path))]
    return str(int(max(mtimes))) if mtimes else '1'


ASSET_VERSION = _asset_version()


def _error(message, status):
    return {"error": message}, status


def _request_language(body) -> str:
    language = body.get('language') or language_registry.ENABLED_LANGUAGES[0]
    if not language_registry.is_enabled(language):
        raise ValueError(f'Language "{language}" is not available on this server.')
    return language


@app.route(rootPath+'/')
def main():
    return render_template('main.html', asset_version=ASSET_VERSION)


@app.route(rootPath+'/getAudioFromText', methods=['POST'])
def getAudioFromText():
    body = request.get_json(force=True, silent=True) or {}
    text = str(body.get('value', '')).strip()
    if not text:
        return _error('No text to read.', 400)
    if len(text) > lambdaGetSample.MAX_CUSTOM_TEXT_CHARS * 2:
        return _error('Text is too long.', 400)
    try:
        language = _request_language(body)
    except ValueError as e:
        return _error(str(e), 400)

    # Prefer Piper on any OS where it is installed; it is fast and natural-sounding.
    if piperTTS.is_available() and language in piperTTS.VOICE_CONFIGS:
        try:
            wav_b64 = piperTTS.generate_wav_base64(text, language=language)
        except Exception as e:
            print('TTS error: ', str(e))
            return _error('Could not generate audio.', 503)
        return {"wavBase64": wav_b64}
    if language == 'de':
        # The Silero fallback only ships a German voice.
        event = {'body': json.dumps({'value': text})}
        result = lambdaTTS.lambda_handler(event, [])
        return json.loads(result['body'])
    # Let the browser fall back to its own speechSynthesis voice.
    return _error('Server-side TTS is not available', 503)


@app.route(rootPath+'/getSample', methods=['POST'])
def getNext():
    body = request.get_json(force=True, silent=True) or {}
    try:
        body['language'] = _request_language(body)
    except ValueError as e:
        return _error(str(e), 400)
    event = {'body': json.dumps(body)}
    return lambdaGetSample.lambda_handler(event, [])


@app.route(rootPath+'/getCustomSample', methods=['POST'])
def getCustomSample():
    body = request.get_json(force=True, silent=True) or {}
    try:
        language = _request_language(body)
        result = lambdaGetSample.custom_sample(str(body.get('text', '')), language)
    except ValueError as e:
        return _error(str(e), 400)
    return result


@app.route(rootPath+'/GetAccuracyFromRecordedAudio', methods=['POST'])
def GetAccuracyFromRecordedAudio():
    body = request.get_json(force=True, silent=True) or {}
    try:
        body['language'] = _request_language(body)
    except ValueError as e:
        return _error(str(e), 400)
    if not str(body.get('title', '')).strip():
        return _error('There is no sentence to compare with.', 400)
    if not body.get('base64Audio'):
        return _error('No audio was received.', 400)

    try:
        event = {'body': json.dumps(body)}
        lambda_correct_output = lambdaSpeechToScore.lambda_handler(event, [])
    except lambdaSpeechToScore.NoSpeechError:
        return _error("We couldn't recognise any speech.", 422)
    except Exception as e:
        print('Error: ', repr(e))
        return _error('Could not process the recording.', 500)

    return lambda_correct_output


def _warm_up_models():
    """Load ASR models in the background so the first user does not wait for them."""
    languages = [lang.strip() for lang in os.environ.get('PRELOAD_LANGUAGES', 'en').split(',') if lang.strip()]
    for lang in languages:
        if not language_registry.is_enabled(lang):
            continue
        try:
            lambdaSpeechToScore.warm_up(lang)
            print(f'Warm-up done for "{lang}"')
        except Exception as e:
            print(f'Warm-up failed for "{lang}": {e}')


if __name__ == "__main__":
    threading.Thread(target=_warm_up_models, daemon=True).start()
    if os.environ.get('OPEN_BROWSER', '1') == '1':
        webbrowser.open_new('http://127.0.0.1:3000/')
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', '3000')))
