import os
import torch
from transformers import pipeline
from transformers.utils import logging as transformers_logging
from ModelInterfaces import IASRModel
from typing import Optional, Union
import numpy as np

import model_pins

# transformers has its own log handler. Like every library, it logs errors
# only: it warns on every transcription that max_new_tokens overrides the
# checkpoint's max_length. Its progress bars ("Loading weights") would put
# lines that are not JSON in the log.
transformers_logging.set_verbosity_error()
transformers_logging.disable_progress_bar()


def clean_up_spaces(text: str) -> str:
    """Remove the space Whisper's tokenizer leaves before punctuation and
    contractions ("raining ?" -> "raining?"), as transformers 4 did. Whisper's
    word timestamps attach punctuation to the word before it, so the
    transcript's words must too, or the two lists fall out of step."""
    for spaced, joined in ((' .', '.'), (' ?', '?'), (' !', '!'), (' ,', ','), (" ' ", "'"),
                           (" n't", "n't"), (" 'm", "'m"), (" 's", "'s"), (" 've", "'ve"), (" 're", "'re")):
        text = text.replace(spaced, joined)
    return text


class WhisperASRModel(IASRModel):
    def __init__(self, model_name: Optional[str] = None, language: Optional[str] = None):
        # A Hugging Face repo id, or a directory with the model files (the Docker
        # image has them in /models/whisper-base).
        model_name = model_name or os.environ.get('WHISPER_MODEL') or model_pins.WHISPER_REPO
        # The default checkpoint is pinned to one commit.
        revision = model_pins.WHISPER_REVISION if model_name == model_pins.WHISPER_REPO else None
        self.asr = pipeline("automatic-speech-recognition", model=model_name, revision=revision,
                            return_timestamps="word")
        self._transcript = ""
        self._word_locations = []
        self.sample_rate = 16000
        # Cap the output length: on silence or noise Whisper can hallucinate the
        # same phrase hundreds of times, which takes close to a minute on CPU.
        # 160 tokens comfortably covers a 300-character practice text.
        self._generate_kwargs = {"max_new_tokens": int(os.environ.get('WHISPER_MAX_NEW_TOKENS', '160'))}
        # Pin the language on multilingual checkpoints. Without this Whisper
        # auto-detects it, and a learner's accent can make it transcribe (or
        # translate) into the wrong language. English-only ".en" checkpoints
        # reject the argument, so it is skipped for them.
        if language and not os.path.basename(os.path.normpath(model_name)).endswith('.en'):
            self._generate_kwargs.update({"language": language, "task": "transcribe"})

    def processAudio(self, audio: Union[np.ndarray, torch.Tensor]):
        # 'audio' can be a path to a file or a numpy array of audio samples.
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().numpy()
        result = self.asr(audio[0], generate_kwargs=self._generate_kwargs)
        self._transcript = clean_up_spaces(result["text"])

        word_locations = []
        previous_end = 0.0
        for word_info in result.get("chunks", []):
            start, end = word_info["timestamp"]
            if start is None:
                start = previous_end
            if end is None:
                end = start + 1
            previous_end = end
            word_locations.append({"word": word_info["text"],
                                   "start_ts": start * self.sample_rate,
                                   "end_ts": end * self.sample_rate,
                                   "tag": "processed"})
        self._word_locations = word_locations

    def getTranscript(self) -> str:
        return self._transcript

    def getWordLocations(self) -> list:
        return self._word_locations
