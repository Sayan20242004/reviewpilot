import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
import jwt


API = "https://api.github.com"


class GitHubAccessError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str = "GitHub repository access failed",
    ):
        self.status_code = status_code
        super().__init__(message)


def _app_id() -> str:
    value = os.environ.get("GITHUB_APP_ID", "").strip()
    if not value:
        raise RuntimeError("GITHUB_APP_ID is not configured")
    return value


def _private_key() -> str:
    # Render: read the complete PEM contents from an environment variable.
    inline = os.environ.get("GITHUB_PRIVATE_KEY", "").strip()
    if inline:
        # Support environment variables containing literal \n sequences.
        return inline.replace("\\n", "\n")

    # Local development: read the PEM from the existing file path.
    path = os.environ.get(
        "GITHUB_PRIVATE_KEY_PATH",
        "./reviewpilot-private-key.pem",
    )
    key_path = Path(path)

    if not key_path.is_absolute():
        key_path = Path(__file__).resolve().parent.parent / key_path

    if not key_path.is_file():
        raise RuntimeError(
            f"GitHub App private key file not found: {key_path}"
        )

    return key_path.read_text(encoding="utf-8")


def create_app_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 8 * 60,
        "iss": _app_id(),
    }
    return jwt.encode(payload, _private_key(), algorithm="RS256")


def _app_headers(extra: dict | None = None) -> dict:
    return {
        "Authorization": f"Bearer {create_app_jwt()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **(extra or {}),
    }


def _token_headers(token: str, extra: dict | None = None) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        **(extra or {}),
    }


def parse_pr_url(url: str):
    match = re.fullmatch(
        r"https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)/?",
        url.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            "Enter a valid GitHub PR URL: "
            "https://github.com/owner/repo/pull/123"
        )

    owner, repo = match.group(1), match.group(2)

    if (
        owner in (".", "..")
        or repo in (".", "..")
        or owner.startswith("-")
        or repo.startswith("-")
    ):
        raise ValueError("Invalid GitHub repository URL")

    return owner, repo.removesuffix(".git"), int(match.group(3))


def _request_or_access_error(response: httpx.Response) -> None:
    if response.status_code in (401, 403, 404):
        raise GitHubAccessError(
            response.status_code,
            f"GitHub returned {response.status_code}",
        )
    response.raise_for_status()


def fetch_diff(
    owner: str,
    repo: str,
    number: int,
    token: str | None = None,
) -> str:
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = httpx.get(
        f"{API}/repos/{owner}/{repo}/pulls/{number}",
        headers=headers,
        timeout=40,
        follow_redirects=False,
    )
    _request_or_access_error(response)
    return response.text


def create_installation_token(installation_id: int) -> str:
    response = httpx.post(
        f"{API}/app/installations/{installation_id}/access_tokens",
        headers=_app_headers(),
        json={},
        timeout=20,
    )
    _request_or_access_error(response)

    token = response.json().get("token")
    if not token:
        raise RuntimeError(
            "GitHub did not return an installation access token"
        )

    return token


def list_app_installations() -> list[dict[str, Any]]:
    response = httpx.get(
        f"{API}/app/installations",
        headers=_app_headers(),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def list_user_installations(user_token: str) -> list[dict[str, Any]]:
    """List GitHub App installations accessible to the authenticated user."""
    installations = []
    page = 1

    while True:
        response = httpx.get(
            f"{API}/user/installations",
            headers=_token_headers(user_token),
            params={"per_page": 100, "page": page},
            timeout=20,
        )
        _request_or_access_error(response)

        batch = response.json().get("installations", [])
        installations.extend(batch)

        if len(batch) < 100:
            break

        page += 1

    return installations


def list_installation_repositories(
    installation_id: int,
) -> list[dict[str, Any]]:
    token = create_installation_token(installation_id)
    response = httpx.get(
        f"{API}/installation/repositories",
        headers=_token_headers(token),
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("repositories", [])


def post_comment(
    owner: str,
    repo: str,
    number: int,
    body: str,
    token: str | None = None,
):
    headers = (
        _token_headers(token)
        if token
        else {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )

    response = httpx.post(
        f"{API}/repos/{owner}/{repo}/issues/{number}/comments",
        json={"body": body},
        headers=headers,
        timeout=30,
    )
    _request_or_access_error(response)
    return response.json()
