import pytest

from agents.pa.agent import _save_recipe_signal, detect_signals


def test_positive_signal_detected():
    has_pos, has_neg = detect_signals("He loved the lentil soup!")
    assert has_pos is True
    assert has_neg is False


def test_negative_signal_detected():
    has_pos, has_neg = detect_signals("He didn't like the tofu scramble")
    assert has_pos is False
    assert has_neg is True


def test_no_signal_neutral_message():
    has_pos, has_neg = detect_signals("What should we have for dinner?")
    assert has_pos is False
    assert has_neg is False


def test_positive_signal_case_insensitive():
    has_pos, _ = detect_signals("That recipe was a HIT")
    assert has_pos is True


def test_negative_signal_case_insensitive():
    _, has_neg = detect_signals("He HATED the spinach puree")
    assert has_neg is True


def test_both_signals_simultaneously():
    has_pos, has_neg = detect_signals(
        "He loved the pasta but won't eat the spinach puree"
    )
    assert has_pos is True
    assert has_neg is True


def test_favorite_keyword():
    has_pos, _ = detect_signals("That's his favorite recipe so far")
    assert has_pos is True


def test_avoid_keyword():
    _, has_neg = detect_signals("Let's avoid that one in future")
    assert has_neg is True



def test_save_recipe_signal_rejects_invalid_signal_type(monkeypatch):
    monkeypatch.setattr(
        "agents.pa.agent._extract_recipe_name", lambda msg, st: "Test Recipe"
    )
    with pytest.raises(KeyError):
        _save_recipe_signal("loved the soup", "invalid_type")
