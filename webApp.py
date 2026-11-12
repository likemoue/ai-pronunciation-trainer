from flask import Flask, render_template, request
import webbrowser
import os
import threading
from flask_cors import CORS
import json

import lambdaTTS
import lambdaSpeechToScore
import lambdaGetSample
import piperTTS

app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = '*'

rootPath = ''


@app.route(rootPath+'/')
def main():
    return render_template('main.html')


@app.route(rootPath+'/getAudioFromText', methods=['POST'])
def getAudioFromText():
    body = request.get_json(force=True)
    text = body.get('value', '')
    language = body.get('language', 'en')
    # Prefer Piper on any OS where it is installed; it is fast and natural-sounding.
    if piperTTS.is_available() and language in piperTTS.VOICE_CONFIGS:
        wav_b64 = piperTTS.generate_wav_base64(text, language=language)
        return {"wavBase64": wav_b64}
    if language == 'de':
        # The Silero fallback only ships a German voice.
        event = {'body': json.dumps(body)}
        result = lambdaTTS.lambda_handler(event, [])
        return json.loads(result['body'])
    # Let the browser fall back to its own speechSynthesis voice.
    return {"error": "Server-side TTS is not available"}, 503


@app.route(rootPath+'/getSample', methods=['POST'])
def getNext():
    event = {'body':  json.dumps(request.get_json(force=True))}
    return lambdaGetSample.lambda_handler(event, [])


@app.route(rootPath+'/GetAccuracyFromRecordedAudio', methods=['POST'])
def GetAccuracyFromRecordedAudio():

    try:
        event = {'body': json.dumps(request.get_json(force=True))}
        lambda_correct_output = lambdaSpeechToScore.lambda_handler(event, [])
    except Exception as e:
        print('Error: ', str(e))
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Headers': '*',
                'Access-Control-Allow-Credentials': "true",
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'OPTIONS,POST,GET'
            },
            'body': ''
        }

    return lambda_correct_output


def _warm_up_models():
    """Load ASR models in the background so the first user does not wait for them."""
    languages = [lang.strip() for lang in os.environ.get('PRELOAD_LANGUAGES', 'en').split(',') if lang.strip()]
    for lang in languages:
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
