import os
import threading
import time

import anthropic


class ClaudeAPIError(Exception):
    pass


_client = None
_client_lock = threading.Lock()


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def complete(
    system_prompt: str,
    messages: list[dict],
    model: str,
    max_tokens: int = 1024,
) -> tuple[str, dict]:
    client = _get_client()
    last_error = None

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
            if not response.content:
                raise ClaudeAPIError("Claude API returned empty content")
            usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
            return response.content[0].text, usage
        except (anthropic.RateLimitError, anthropic.InternalServerError) as e:
            last_error = e
            time.sleep(2**attempt)
        except anthropic.APIError as e:
            raise ClaudeAPIError(f"Claude API error: {e}") from e

    raise ClaudeAPIError(f"Claude API failed after 3 attempts: {last_error}") from last_error
