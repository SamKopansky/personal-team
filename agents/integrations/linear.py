"""Linear API client (GraphQL over HTTPS)."""
import os

import requests

LINEAR_API_URL = "https://api.linear.app/graphql"


def _headers() -> dict:
    return {
        "Authorization": os.environ["LINEAR_API_KEY"],
        "Content-Type": "application/json",
    }


def _gql(query: str, variables: dict | None = None) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    r = requests.post(LINEAR_API_URL, json=payload, headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"Linear API error: {data['errors']}")
    return data["data"]


def get_board_summary() -> dict:
    """Return tickets grouped by state: in_progress, ready, in_review, blocked."""
    query = """
    {
      issues(filter: { state: { type: { in: ["started", "unstarted"] } } }) {
        nodes {
          id
          identifier
          title
          state { name type }
          priority
          updatedAt
        }
      }
    }
    """
    data = _gql(query)
    result: dict[str, list] = {"in_progress": [], "ready": [], "in_review": [], "blocked": []}
    for issue in data["issues"]["nodes"]:
        state_name = issue["state"]["name"].lower()
        state_type = issue["state"]["type"]
        if "review" in state_name:
            result["in_review"].append(issue)
        elif "block" in state_name:
            result["blocked"].append(issue)
        elif state_type == "started":
            result["in_progress"].append(issue)
        else:
            result["ready"].append(issue)
    return result


def get_ready_tickets() -> list:
    """Return unstarted tickets ordered by priority (1=urgent … 4=low, 0=none)."""
    query = """
    {
      issues(
        filter: { state: { type: { eq: "unstarted" } } }
        orderBy: priority
      ) {
        nodes {
          id
          identifier
          title
          description
          priority
          updatedAt
        }
      }
    }
    """
    data = _gql(query)
    return data["issues"]["nodes"]


def get_ticket(identifier: str) -> dict | None:
    """Get a single ticket by identifier (e.g. ENG-42)."""
    query = """
    query($filter: IssueFilter!) {
      issues(filter: $filter) {
        nodes {
          id
          identifier
          title
          description
          state { name }
          priority
          updatedAt
        }
      }
    }
    """
    data = _gql(query, {"filter": {"identifier": {"eq": identifier}}})
    nodes = data["issues"]["nodes"]
    return nodes[0] if nodes else None


def get_teams() -> list:
    """Return all teams with id and name."""
    query = "{ teams { nodes { id name } } }"
    return _gql(query)["teams"]["nodes"]


def get_workflow_states(team_id: str) -> list:
    """Return workflow states for a team."""
    query = """
    query($teamId: String!) {
      workflowStates(filter: { team: { id: { eq: $teamId } } }) {
        nodes { id name type }
      }
    }
    """
    return _gql(query, {"teamId": team_id})["workflowStates"]["nodes"]


def create_ticket(team_id: str, title: str, description: str = "") -> dict:
    """Create a ticket. Returns {id, identifier, title}."""
    mutation = """
    mutation($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue { id identifier title }
      }
    }
    """
    data = _gql(
        mutation,
        {"input": {"teamId": team_id, "title": title, "description": description}},
    )
    return data["issueCreate"]["issue"]


def update_ticket_status(ticket_id: str, state_id: str) -> bool:
    """Update ticket to a new state by state UUID."""
    mutation = """
    mutation($id: String!, $stateId: String!) {
      issueUpdate(id: $id, input: { stateId: $stateId }) {
        success
      }
    }
    """
    return _gql(mutation, {"id": ticket_id, "stateId": state_id})["issueUpdate"]["success"]
