from app.core.frame_analyzer import BasicFrameAnalyzer
from app.models import CapturedFrame


def make_frame(value: int, timestamp: float) -> CapturedFrame:
    width = 8
    height = 8
    pixel = bytes([value, value, value, 255])
    return CapturedFrame(
        width=width,
        height=height,
        timestamp=timestamp,
        image=pixel * width * height,
    )


def test_frame_analyzer_detects_idle_after_static_window() -> None:
    analyzer = BasicFrameAnalyzer(sample_width=4, sample_height=4)

    analyzer.analyze(make_frame(10, 0.0))
    stats, scene = analyzer.analyze(make_frame(10, 11.0))

    assert stats.pace == "idle"
    assert stats.static_seconds >= 10.0
    assert scene.event == "idle"
    assert scene.activity == "idle"


def test_frame_analyzer_detects_highlight_on_large_change() -> None:
    analyzer = BasicFrameAnalyzer(sample_width=4, sample_height=4)

    analyzer.analyze(make_frame(0, 0.0))
    stats, scene = analyzer.analyze(make_frame(255, 1.0))

    assert stats.pace == "fast"
    assert stats.change_ratio > 0.25
    assert scene.event == "highlight"
