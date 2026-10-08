import hmac
import hashlib
import os
import httpx

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import gh
from .agent import run_review


load_dotenv()

app = FastAPI(title="ReviewPilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173"
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReviewIn(BaseModel):
    pr_url: str
    github_token: str | None = None


def valid_signature(
    body: bytes,
    sig: str | None,
    secret: str
) -> bool:
    if not sig or not sig.startswith("sha256="):
        return False

    expected = (
        "sha256="
        + hmac.new(
            secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
    )

    return hmac.compare_digest(expected, sig)


def to_markdown(r: dict) -> str:
    return (
        "## ReviewPilot\n\n"
        f"**Summary**\n{r['plan']}\n\n"
        f"**Review**\n{r['review']}\n\n"
        f"**Suggested tests**\n{r['tests']}"
    )


def review_and_comment(owner, repo, n):
    diff = gh.fetch_diff(owner, repo, n)

    review = run_review(diff)

    gh.post_comment(
        owner,
        repo,
        n,
        to_markdown(review)
    )


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/review")
def review(body: ReviewIn):
    try:
        owner, repo, n = gh.parse_pr_url(body.pr_url)

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    try:
        diff = gh.fetch_diff(
            owner,
            repo,
            n,
            token=body.github_token
        )

        return run_review(diff)

    except httpx.HTTPStatusError as e:
        status = e.response.status_code

        if status in (401, 403, 404):
            if body.github_token:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "The GitHub token does not have permission "
                        "to access this repository or pull request."
                    )
                )

            raise HTTPException(
                status_code=403,
                detail=(
                    "This pull request is not publicly accessible. "
                    "Enter a GitHub token with access to this repository."
                )
            )

        raise HTTPException(
            status_code=502,
            detail=f"GitHub request failed: {status}"
        )

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"review failed: {type(e).__name__}: {e}"
        )


@app.post("/webhook")
async def webhook(
    req: Request,
    tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    body = await req.body()

    secret = os.environ.get(
        "GITHUB_WEBHOOK_SECRET",
        ""
    )

    if not secret or not valid_signature(
        body,
        x_hub_signature_256,
        secret
    ):
        raise HTTPException(
            status_code=401,
            detail="bad signature"
        )

    if x_github_event != "pull_request":
        return {
            "skipped": x_github_event
        }

    p = await req.json()

    if p.get("action") not in (
        "opened",
        "synchronize"
    ):
        return {
            "skipped": p.get("action")
        }

    owner, repo = p["repository"]["full_name"].split("/")

    n = p["pull_request"]["number"]

    tasks.add_task(
        review_and_comment,
        owner,
        repo,
        n
    )

    return {
        "queued": n
    }