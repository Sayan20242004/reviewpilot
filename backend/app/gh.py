import os
import re
import httpx


def _headers(extra=None, token=None):
    h = {
        "X-GitHub-Api-Version": "2022-11-28",
        **(extra or {}),
    }

    if token:
        h["Authorization"] = f"Bearer {token}"

    return h


def parse_pr_url(url: str):
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError("not a GitHub PR url")
    return m[1], m[2], int(m[3])


def fetch_diff(owner, repo, n, token=None) -> str:
    r = httpx.get(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{n}",
        headers=_headers(
            {"Accept": "application/vnd.github.v3.diff"},
            token=token,
        ),
        timeout=30,
    )

    r.raise_for_status()
    return r.text


def post_comment(owner, repo, n, body: str):
    httpx.post(
        f"https://api.github.com/repos/{owner}/{repo}/issues/{n}/comments",
        json={"body": body},
        headers=_headers(
            token=os.environ.get("GITHUB_TOKEN")
        ),
        timeout=30,
    ).raise_for_status()