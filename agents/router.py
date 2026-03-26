import json
import logging

from agents.claude_client import ClaudeAPIError, complete

_log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
AUTO_ROUTE_THRESHOLD = 0.75

_SYSTEM_PROMPT = (
    "You are a message router for a personal agentic team. "
    "Classify the incoming message to the best agent.\n\n"
    "Agents:\n"
    "- pa: Personal assistant — personal life, shopping, parenting, recipes, "
    "baby/infant questions, travel, general Q&A\n"
    "- manager: Dev manager — software project questions, feature ideas, Linear board "
    "status, ticket creation, prioritization, sprint planning, development work\n"
    "- researcher: Technical researcher — architecture comparisons, library selection, "
    "deep technical investigations requiring research\n\n"
    "Rules:\n"
    '- Free-form coding or dev requests route to "manager" (not "researcher" or "pa")\n'
    "- If confidence is below 0.75, return \"clarify\"\n"
    "- Return ONLY valid JSON — no markdown, no extra text\n\n"
    'Response format: {"agent": "<agent>", "confidence": <0.0-1.0>, "reason": "<one sentence>"}'
)


def route(message: str) -> dict:
    """Classify a free-form message. Returns {agent, confidence, reason}.

    agent is one of: pa, manager, researcher, clarify
    Note: developer is never returned — free-form dev requests go to manager first.
    """
    try:
        response_text, _ = complete(
            system_prompt=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
            model=MODEL,
            max_tokens=100,
        )
        data = json.loads(response_text.strip())
        agent = str(data.get("agent", "clarify"))
        # developer is never a direct free-form target — always route via manager
        if agent == "developer":
            agent = "manager"
        confidence = float(data.get("confidence", 0.0))
        reason = str(data.get("reason", ""))
        return {"agent": agent, "confidence": confidence, "reason": reason}
    except (ClaudeAPIError, json.JSONDecodeError, ValueError, KeyError) as e:
        _log.warning("Router error: %s", e)
        return {"agent": "clarify", "confidence": 0.0, "reason": "Router error"}
