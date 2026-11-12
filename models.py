import torch
import torch.nn as nn
from ModelInterfaces import IASRModel
from AIModels import NeuralASR

def getASRModel(language: str,use_whisper:bool=True) -> IASRModel:

    if use_whisper:
        import language_registry
        from whisper_wrapper import WhisperASRModel
        return WhisperASRModel(language=language_registry.get(language).asr_language)
    
    if language == 'de':

        model, decoder, utils = torch.hub.load(repo_or_dir='snakers4/silero-models',
                                               model='silero_stt',
                                               language='de',
                                               device=torch.device('cpu'),
                                               trust_repo=True)
        model.eval()
        return NeuralASR(model, decoder)

    elif language == 'en':
        model, decoder, utils = torch.hub.load(repo_or_dir='snakers4/silero-models',
                                               model='silero_stt',
                                               language='en',
                                               device=torch.device('cpu'),
                                               trust_repo=True)
        model.eval()
        return NeuralASR(model, decoder)
    elif language == 'fr':
        model, decoder, utils = torch.hub.load(repo_or_dir='snakers4/silero-models',
                                               model='silero_stt',
                                               language='fr',
                                               device=torch.device('cpu'),
                                               trust_repo=True)
        model.eval()
        return NeuralASR(model, decoder)
    else:
        raise ValueError('Language not implemented')


def getTTSModel(language: str) -> nn.Module:

    if language == 'de':

        speaker = 'thorsten_v2'  # 16 kHz
        model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models',
                                  model='silero_tts',
                                  language=language,
                                  speaker=speaker,
                                  trust_repo=True)

    elif language == 'en':
        speaker = 'lj_16khz'  # 16 kHz
        model = torch.hub.load(repo_or_dir='snakers4/silero-models',
                               model='silero_tts',
                               language=language,
                               speaker=speaker,
                               trust_repo=True)
    else:
        raise ValueError('Language not implemented')

    return model
