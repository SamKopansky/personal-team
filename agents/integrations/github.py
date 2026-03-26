"""GitHub REST API v3 client."""
import os

import requests

_GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_open_prs(repo: str) -> list:
    """List open PRs for repo (format: owner/repo)."""
    r = requests.get(
        f"{_GITHUB_API}/repos/{repo}/pulls",
        params={"state": "open"},
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_default_branch_sha(repo: str) -> str:
    """Return the HEAD SHA of the default branch."""
    r = requests.get(f"{_GITHUB_API}/repos/{repo}", headers=_headers(), timeout=30)
    r.raise_for_status()
    default_branch = r.json()["default_branch"]
    r2 = requests.get(
        f"{_GITHUB_API}/repos/{repo}/git/ref/heads/{default_branch}",
        headers=_headers(),
        timeout=30,
    )
    r2.raise_for_status()
    return r2.json()["object"]["sha"]


def create_branch(repo: str, branch_name: str, sha: str) -> bool:
    """Create a new branch from a given SHA. Returns True on success."""
    payload = {"ref": f"refs/heads/{branch_name}", "sha": sha}
    r = requests.post(
        f"{_GITHUB_API}/repos/{repo}/git/refs",
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return True


def create_pr(repo: str, title: str, body: str, head: str, base: str = "main") -> dict:
    """Open a pull request. Returns the PR object (includes html_url, number)."""
    payload = {"title": title, "body": body, "head": head, "base": base}
    r = requests.post(
        f"{_GITHUB_API}/repos/{repo}/pulls",
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
