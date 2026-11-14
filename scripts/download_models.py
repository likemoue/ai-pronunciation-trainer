"""Download the pinned model files into the Docker image (see model_pins.py).

    python scripts/download_models.py

Standard library only, so the Docker stage that runs it does not depend on
requirements.lock.

* Whisper: the files of WHISPER_REVISION go to WHISPER_DIR (default
  /models/whisper-base).
* Piper: the voice named by PIPER_VOICE_EN (default model_pins.DEFAULT_ENGLISH_VOICE)
  goes to PIPER_MODEL_DIR (default /models/piper).

Every file is checked against its pinned sha256.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import model_pins  # noqa: E402


def main():
    whisper_dir = os.environ.get('WHISPER_DIR', '/models/whisper-base')
    model_pins.download_whisper(whisper_dir)
    for name in sorted(model_pins.WHISPER_FILES):
        print(f'{model_pins.WHISPER_REPO}@{model_pins.WHISPER_REVISION[:7]}: {name} ok')

    voice = os.environ.get('PIPER_VOICE_EN') or model_pins.DEFAULT_ENGLISH_VOICE
    piper_dir = os.environ.get('PIPER_MODEL_DIR', '/models/piper')
    model_pins.download_piper_voice(voice, piper_dir)
    for suffix in model_pins.PIPER_VOICE_FILES:
        print(f'{voice}{suffix}: ok')


if __name__ == '__main__':
    main()
