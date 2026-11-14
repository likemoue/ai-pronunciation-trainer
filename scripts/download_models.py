"""Download the pinned model files into the Docker image (see model_pins.py).

    python scripts/download_models.py

* Whisper: the files of WHISPER_REVISION go to WHISPER_DIR (default
  /models/whisper-base), without the weights in formats the app does not load.
* Piper: the voice named by PIPER_VOICE_EN (default model_pins.DEFAULT_ENGLISH_VOICE)
  goes to PIPER_MODEL_DIR (default /models/piper); each file is checked against
  its pinned sha256.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import model_pins  # noqa: E402


def main():
    from huggingface_hub import snapshot_download

    whisper_dir = os.environ.get('WHISPER_DIR', '/models/whisper-base')
    snapshot_download(model_pins.WHISPER_REPO, revision=model_pins.WHISPER_REVISION,
                      local_dir=whisper_dir, ignore_patterns=model_pins.WHISPER_IGNORE_PATTERNS)
    # Download metadata that snapshot_download keeps next to the files.
    shutil.rmtree(os.path.join(whisper_dir, '.cache'), ignore_errors=True)
    for name in sorted(os.listdir(whisper_dir)):
        print(f'{model_pins.WHISPER_REPO}@{model_pins.WHISPER_REVISION[:7]}: {name}')

    voice = os.environ.get('PIPER_VOICE_EN') or model_pins.DEFAULT_ENGLISH_VOICE
    piper_dir = os.environ.get('PIPER_MODEL_DIR', '/models/piper')
    model_pins.download_piper_voice(voice, piper_dir)
    for suffix in model_pins.PIPER_VOICE_FILES:
        print(f'{voice}{suffix}: sha256 {model_pins.sha256(os.path.join(piper_dir, voice + suffix))}')


if __name__ == '__main__':
    main()
