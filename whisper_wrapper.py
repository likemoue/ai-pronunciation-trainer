import os
import torch
from transformers import pipeline
from ModelInterfaces import IASRModel
from typing import Optional, Union
import numpy as np


class WhisperASRModel(IASRModel):
    def __init__(self, model_name: Optional[str] = None, language: Optional[str] = None):
        model_name = model_name or os.environ.get('WHISPER_MODEL', 'openai/whisper-base')
        self.asr = pipeline("automatic-speech-recognition", model=model_name, return_timestamps="word")
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
        if language and not model_name.endswith('.en'):
            self._generate_kwargs.update({"language": language, "task": "transcribe"})

    def processAudio(self, audio: Union[np.ndarray, torch.Tensor]):
        # 'audio' can be a path to a file or a numpy array of audio samples.
        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().numpy()
        result = self.asr(audio[0], generate_kwargs=self._generate_kwargs)
        self._transcript = result["text"]

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
