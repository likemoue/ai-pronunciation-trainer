"""End-to-end check with the real models (Whisper + Piper). Run with: pytest -m slow"""
import pytest

pytestmark = pytest.mark.slow


def test_strict_warm_up_scores_a_spoken_sentence():
    import lambdaSpeechToScore
    assert lambdaSpeechToScore.warm_up('en', strict=True) is True
