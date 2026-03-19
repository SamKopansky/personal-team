from unittest.mock import MagicMock, patch
from agents.claude_client import complete


@patch("agents.claude_client._get_client")
def test_complete_returns_text_and_usage(mock_get_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello")]
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_get_client.return_value.messages.create.return_value = mock_response

    text, usage = complete(
        system_prompt="test",
        messages=[{"role": "user", "content": "hi"}],
        model="claude-haiku-4-5",
    )
    assert text == "Hello"
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 5
