from unittest.mock import patch

from agents import router


def test_route_personal_message_returns_pa():
    with patch("agents.router.complete") as mock:
        mock.return_value = ('{"agent": "pa", "confidence": 0.92, "reason": "personal"}', {})
        result = router.route("find good shoes for a new walker under $50")
    assert result["agent"] == "pa"
    assert result["confidence"] == 0.92


def test_route_project_message_returns_manager():
    with patch("agents.router.complete") as mock:
        mock.return_value = (
            '{"agent": "manager", "confidence": 0.88, "reason": "project status question"}',
            {},
        )
        result = router.route("what are we working on this week?")
    assert result["agent"] == "manager"


def test_route_developer_redirected_to_manager():
    """Free-form dev requests must route to manager, never directly to developer."""
    with patch("agents.router.complete") as mock:
        mock.return_value = (
            '{"agent": "developer", "confidence": 0.9, "reason": "dev task"}',
            {},
        )
        result = router.route("fix the login bug")
    assert result["agent"] == "manager"


def test_route_researcher_passes_through():
    with patch("agents.router.complete") as mock:
        mock.return_value = (
            '{"agent": "researcher", "confidence": 0.85, "reason": "technical comparison"}',
            {},
        )
        result = router.route("compare Supabase vs PlanetScale for my use case")
    assert result["agent"] == "researcher"


def test_route_low_confidence_returns_clarify():
    with patch("agents.router.complete") as mock:
        mock.return_value = (
            '{"agent": "pa", "confidence": 0.5, "reason": "ambiguous"}',
            {},
        )
        result = router.route("what about tomorrow")
    # router itself passes through the low confidence — bot.py applies threshold
    assert result["confidence"] == 0.5
    assert result["agent"] == "pa"


def test_route_explicit_clarify_from_model():
    with patch("agents.router.complete") as mock:
        mock.return_value = (
            '{"agent": "clarify", "confidence": 0.4, "reason": "unclear intent"}',
            {},
        )
        result = router.route("hm")
    assert result["agent"] == "clarify"


def test_route_invalid_json_returns_clarify():
    with patch("agents.router.complete") as mock:
        mock.return_value = ("not json at all", {})
        result = router.route("anything")
    assert result["agent"] == "clarify"
    assert result["confidence"] == 0.0


def test_route_api_error_returns_clarify():
    from agents.claude_client import ClaudeAPIError

    with patch("agents.router.complete", side_effect=ClaudeAPIError("timeout")):
        result = router.route("test")
    assert result["agent"] == "clarify"
    assert result["confidence"] == 0.0


def test_auto_route_threshold_value():
    assert router.AUTO_ROUTE_THRESHOLD == 0.75
