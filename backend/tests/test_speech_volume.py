from app.speech_volume import (
    DEFAULT_SPEECH_VOLUME_PERCENT,
    clamp_speech_volume_percent,
    volume_percent_to_gain,
)


def test_default_volume_is_balanced_test_level():
    assert DEFAULT_SPEECH_VOLUME_PERCENT == 88
    assert volume_percent_to_gain(88) > 1.0
    assert volume_percent_to_gain(70) == 1.0


def test_clamp_bounds():
    assert clamp_speech_volume_percent(10) == 40
    assert clamp_speech_volume_percent(200) == 150
    assert clamp_speech_volume_percent("bad") == DEFAULT_SPEECH_VOLUME_PERCENT
