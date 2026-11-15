from ModelInterfaces import IASRModel


def getASRModel(language: str, use_whisper: bool = True) -> IASRModel:
    """Speech recogniser for a language. Every supported language uses Whisper."""
    if not use_whisper:
        raise ValueError('Only the Whisper ASR backend is supported.')
    import language_registry
    from whisper_wrapper import WhisperASRModel
    return WhisperASRModel(language=language_registry.get(language).asr_language)
