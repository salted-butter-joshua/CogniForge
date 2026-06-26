"""Tests for observer report formatting."""
from src.tools.learning_policy import format_observer_report


def test_format_observer_report_fields():
    obs = {
        "observer_summary": "偏好罗列概念，缺少因果链",
        "learning_patterns": "每轮增量整理但很少删除旧误解",
        "knowledge_framework": "树状框架有二层，深层链接薄弱",
        "note_style_observations": "口语化概括为主",
        "recurring_blind_spots": "异常处理反复遗漏",
    }
    text = format_observer_report(obs)
    assert "偏好罗列概念" in text
    assert "因果链" in text
    assert "异常处理" in text
    assert "口语化" in text


def test_format_observer_report_empty():
    assert format_observer_report({}) == ""
