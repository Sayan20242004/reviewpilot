import hashlib
import hmac
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, Field

from . import gh
from .agent import run_review

load_dotenv()

app = FastAPI(title="ReviewPilot")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_APP_SLUG = os.environ.get("GITHUB_APP_SLUG", "")
GITHUB_OAUTH_CALLBACK_URL = os.environ.get(
    "GITHUB_OAUTH_CALLBACK_URL", "http://localhost:8000/auth/github/callback"
)
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE = "reviewpilot_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
OAUTH_STATE_TTL_SECONDS = 10 * 60

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        item.strip()
        for item in os.environ.get("CORS_ORIGINS", FRONTEND_URL).split(",")
        if item.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage is suitable for local development only. Use Redis/database
# sessions for multi-worker or production deployments.
sessions: dict[str, dict[str, Any]] = {}
oauth_states: dict[str, dict[str, Any]] = {}
install_states: dict[str, dict[str, Any]] = {}


class ReviewIn(BaseModel):
    pr_url: str = Field(min_length=1)

class InstallationConnectIn(BaseModel):
    installation_id: int

def valid_signature(body: bytes, sig: str | None, secret: str) -> bool:
    if not sig or not sig.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def to_markdown(review_result: dict) -> str:
    return (
        "## ReviewPilot\n\n"
        f"**Summary**\n{review_result['plan']}\n\n"
        f"**Review**\n{review_result['review']}\n\n"
        f"**Suggested tests**\n{review_result['tests']}"
    )


def _session_id(request: Request) -> str | None:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    record = sessions.get(sid)
    if not record or record.get("expires_at", 0) < time.time():
        sessions.pop(sid, None)
        return None
    record["expires_at"] = time.time() + SESSION_TTL_SECONDS
    return sid


def _session(request: Request) -> dict[str, Any] | None:
    sid = _session_id(request)
    return sessions.get(sid) if sid else None


def _new_session(user: dict, access_token: str) -> str:
    sid = secrets.token_urlsafe(32)
    sessions[sid] = {
        "user": user,
        "oauth_token": access_token,
        "linked_accounts": [
            {"user": user, "oauth_token": access_token}
        ],
        "installation_ids": [],
        "expires_at": time.time() + SESSION_TTL_SECONDS,
    }
    return sid


def _set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )


def _frontend_redirect(query: dict[str, str] | None = None) -> RedirectResponse:
    suffix = f"?{urlencode(query)}" if query else ""
    return RedirectResponse(f"{FRONTEND_URL}/{suffix}", status_code=303)


def _clean_expired_states() -> None:
    now = time.time()
    for store in (oauth_states, install_states):
        for key in list(store):
            if store[key].get("expires_at", 0) < now:
                store.pop(key, None)


def _safe_pr_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        owner, repo, number = gh.parse_pr_url(value)
    except ValueError:
        return None
    return f"https://github.com/{owner}/{repo}/pull/{number}"



def _start_oauth(
    next_path: str = "/",
    *,
    purpose: str = "login",
    session_id: str | None = None,
) -> RedirectResponse:
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            500, "GitHub OAuth is not configured on the backend."
        )

    _clean_expired_states()
    state = secrets.token_urlsafe(32)

    oauth_states[state] = {
        "next_path": (
            next_path
            if next_path.startswith("/") and not next_path.startswith("//")
            else "/"
        ),
        "purpose": purpose,
        "session_id": session_id,
        "expires_at": time.time() + OAUTH_STATE_TTL_SECONDS,
    }

    
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_OAUTH_CALLBACK_URL,
        "scope": "read:user user:email",
        "state": state,
        "prompt": "select_account",
    }


    return RedirectResponse(
        "https://github.com/login/oauth/authorize?"
        + urlencode(params),
        status_code=302,
    )


def _oauth_popup_response(status: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html>
<head><title>ReviewPilot — GitHub</title></head>
<body>
<p>Returning to ReviewPilot...</p>
<script>
  if (window.opener) {{
    window.opener.postMessage(
      {{ type: "reviewpilot-github-oauth", status: "{status}" }},
      window.location.origin
    );
    window.close();
  }} else {{
    window.location.replace("http://localhost:5174/");
  }}
</script>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


def _installation_url(sid: str, pr_url: str | None) -> RedirectResponse:
    if not GITHUB_APP_SLUG:
        raise HTTPException(500, "GITHUB_APP_SLUG is not configured on the backend.")
    _clean_expired_states()
    state = secrets.token_urlsafe(32)
    install_states[state] = {
        "session_id": sid,
        "pr_url": pr_url,
        "expires_at": time.time() + 30 * 60,
    }
    # Configure the GitHub App Setup URL as:
    # http://localhost:8000/auth/installation/callback (local)
    # or your deployed backend's equivalent.
    target = f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new?state={state}"
    return RedirectResponse(target, status_code=302)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/auth/github/login")
def github_login(request: Request, next: str = "/"):
    # Only accept local backend paths to prevent open redirects.
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    return _start_oauth(next)

@app.get("/auth/github/add-account")
def github_add_account(request: Request):
    sid = _session_id(request)
    if not sid or not sessions.get(sid, {}).get("user"):
        raise HTTPException(401, "Sign in to ReviewPilot first.")

    return _start_oauth(
        "/",
        purpose="add_account",
        session_id=sid,
    )


@app.get("/auth/github/callback")
async def github_callback(
    request: Request,
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return _frontend_redirect({
            "auth_error": "github_authorization_denied"
        })

    _clean_expired_states()
    state_record = oauth_states.pop(state or "", None)

    if not state_record or not code:
        return _frontend_redirect({
            "auth_error": "invalid_or_expired_state"
        })

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                json={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": GITHUB_OAUTH_CALLBACK_URL,
                },
            )
            token_response.raise_for_status()

            token_data = token_response.json()
            access_token = token_data.get("access_token")

            if not access_token:
                return _frontend_redirect({
                    "auth_error": "token_exchange_failed"
                })

            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            user_response.raise_for_status()
            user = user_response.json()

    except httpx.HTTPError:
        return _frontend_redirect({
            "auth_error": "github_api_request_failed"
        })

    purpose = state_record.get("purpose", "login")

    # Connect an additional GitHub identity to the existing session.
    if purpose == "add_account":
        sid = state_record.get("session_id")
        session = sessions.get(sid) if sid else None

        if (
            not session
            or session.get("expires_at", 0) < time.time()
            or request.cookies.get(SESSION_COOKIE) != sid
        ):
            return _frontend_redirect({
                "auth_error": "session_expired_adding_account"
            })

        linked_accounts = session.setdefault(
            "linked_accounts",
            [
                {
                    "user": session["user"],
                    "oauth_token": session["oauth_token"],
                }
            ],
        )

        # Avoid linking the same GitHub identity twice.
        existing_ids = {
            str(account["user"].get("id"))
            for account in linked_accounts
        }

        
        if str(user.get("id")) not in existing_ids:
            linked_accounts.append({
                "user": user,
                "oauth_token": access_token,
            })

        session["expires_at"] = time.time() + SESSION_TTL_SECONDS

        redirect = _oauth_popup_response("account_added")
        _set_session_cookie(redirect, sid)
        return redirect

    # Normal login: create a fresh, isolated session.
    old_sid = _session_id(request)
    sid = _new_session(user, access_token)

    if old_sid:
        sessions.pop(old_sid, None)

    next_path = state_record.get("next_path", "/")

    redirect = RedirectResponse(
        f"{str(request.base_url).rstrip('/')}{next_path}",
        status_code=303,
    )
    _set_session_cookie(redirect, sid)

    return redirect



@app.get("/auth/connect")
def auth_connect(request: Request, pr_url: str | None = None):
    safe_pr = _safe_pr_url(pr_url)
    sid = _session_id(request)
    if not sid or not sessions.get(sid, {}).get("user"):
        query = urlencode({"pr_url": safe_pr}) if safe_pr else ""
        next_path = "/auth/connect" + (f"?{query}" if query else "")
        return _start_oauth(next_path)
    return _installation_url(sid, safe_pr)



@app.get("/auth/installation/callback")
def installation_callback(
    request: Request,
    installation_id: str | None = None,
    setup_action: str | None = None,
    state: str | None = None,
):
    _clean_expired_states()
    flow = install_states.pop(state or "", None)

    if not flow or not installation_id:
        return _frontend_redirect({"auth_error": "installation_state_missing"})

    if setup_action == "request":
        return _frontend_redirect({
            "auth_error": "installation_requested_not_completed"
        })

    sid = flow.get("session_id")
    session = sessions.get(sid)

    if not session or session.get("expires_at", 0) < time.time():
        return _frontend_redirect({
            "auth_error": "session_expired_during_installation"
        })

    
    try:
        installation_id_int = int(installation_id)
        gh.create_installation_token(installation_id_int)
        pr_url = flow.get("pr_url")

    except Exception:
        return _frontend_redirect({
            "auth_error": "installation_verification_failed"
        })


    installation_ids = set(
        str(x) for x in session.get("installation_ids", [])
    )
    installation_ids.add(str(installation_id_int))
    session["installation_ids"] = sorted(installation_ids)
    session["expires_at"] = time.time() + SESSION_TTL_SECONDS

    return _frontend_redirect({
        "github": "connected",
        **({"resume_pr": pr_url} if pr_url else {}),
    })



@app.get("/auth/me")
def auth_me(request: Request):
    session = _session(request)
    if not session:
        raise HTTPException(401, "Not signed in with GitHub.")
    return {"user": session["user"]}


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        sessions.pop(sid, None)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}




def _get_accessible_installations(
    session: dict[str, Any],
) -> list[dict]:
    """Discover installations belonging to linked GitHub accounts
    and remember their installation IDs in this session.
    """
    known_ids = {
        str(value)
        for value in session.get("installation_ids", [])
    }

    linked_accounts = session.get("linked_accounts") or [
        {"user": session.get("user", {})}
    ]

    linked_logins = {
        str((account.get("user") or {}).get("login", "")).lower()
        for account in linked_accounts
        if (account.get("user") or {}).get("login")
    }

    try:
        all_installations = gh.list_app_installations()
    except Exception:
        all_installations = []

    results = []
    seen_ids = set()

    for item in all_installations:
        installation_id = str(item.get("id", ""))
        account = (item.get("account") or {}).get("login", "")
        target_type = item.get("target_type", "Account")

        if not installation_id or installation_id in seen_ids:
            continue

        # Include installations already recorded in this session,
        # or installations whose GitHub user account is linked.
        if (
            installation_id not in known_ids
            and account.lower() not in linked_logins
        ):
            continue

        seen_ids.add(installation_id)
        known_ids.add(installation_id)

        results.append({
            "id": int(installation_id),
            "account": account or "Unknown account",
            "target_type": target_type,
        })

    session["installation_ids"] = sorted(known_ids)
    session["expires_at"] = time.time() + SESSION_TTL_SECONDS

    return results





@app.get("/auth/available-installations")
def available_installations(request: Request):
    session = _session(request)
    if not session:
        raise HTTPException(401, "Sign in with GitHub first.")

    linked_accounts = session.get("linked_accounts") or [
        {
            "user": session["user"],
            "oauth_token": session["oauth_token"],
        }
    ]

    connected_ids = {
        str(value)
        for value in session.get("installation_ids", [])
    }

    installations = []
    seen_ids = set()
    errors = []

    for linked in linked_accounts:
        user_token = linked.get("oauth_token")
        user = linked.get("user") or {}

        if not user_token:
            continue

        try:
            available = gh.list_user_installations(user_token)
        except Exception as exc:
            # Preserve the error so an authorization failure isn't
            # silently mistaken for an empty installation list.
            errors.append(
                f"{user.get('login', 'Unknown user')}: {type(exc).__name__}"
            )
            continue

        for item in available:
            installation_id = str(item.get("id"))

            if not installation_id or installation_id in seen_ids:
                    continue
            seen_ids.add(installation_id)

            installations.append({
                "id": int(installation_id),
                "account": (item.get("account") or {}).get(
                    "login", "Unknown account"
                ),
                "target_type": item.get("target_type", "Account"),
                "github_user": user.get("login", "Unknown user"),
            })

    if errors and not installations:
        raise HTTPException(
            502,
            "Could not load installations for linked GitHub accounts. "
            + "; ".join(errors),
        )

    return {"installations": installations}



@app.post("/auth/connect-installation")
def connect_existing_installation(
    body: InstallationConnectIn,
    request: Request,
):
    session = _session(request)
    if not session:
        raise HTTPException(401, "Sign in with GitHub first.")

    linked_accounts = session.get("linked_accounts") or [
        {
            "user": session.get("user", {}),
            "oauth_token": session.get("oauth_token"),
        }
    ]

    installation_id = str(body.installation_id)
    verified = False
    errors = []

    for linked in linked_accounts:
        user_token = linked.get("oauth_token")
        if not user_token:
            continue

        try:
            available = gh.list_user_installations(user_token)
            allowed_ids = {
                str(item.get("id")) for item in available
            }

            if installation_id not in allowed_ids:
                continue

            gh.create_installation_token(int(installation_id))
            verified = True
            break

        except Exception as exc:
            errors.append(type(exc).__name__)

    if not verified:
        raise HTTPException(
            403,
            "Could not verify this installation through any linked "
            "GitHub account. Confirm that the GitHub App is installed "
            "on the intended account and try refreshing installations."
        )

    ids = {
        str(value)
        for value in session.get("installation_ids", [])
    }
    ids.add(installation_id)
    session["installation_ids"] = sorted(ids)
    session["expires_at"] = time.time() + SESSION_TTL_SECONDS

    return {
        "ok": True,
        "installation_id": int(installation_id),
    }


@app.get("/auth/installations")
def auth_installations(request: Request):
    session = _session(request)
    if not session:
        raise HTTPException(401, "Sign in with GitHub first.")
    return {"installations": _get_accessible_installations(session)}


@app.get("/auth/repositories")
def auth_repositories(request: Request, installation_id: str):
    session = _session(request)
    if not session:
        raise HTTPException(401, "Sign in with GitHub first.")
    permitted = {str(x["id"]) for x in _get_accessible_installations(session)}
    if installation_id not in permitted:
        raise HTTPException(403, "This installation is not authorized for your session.")
    try:
        repos = gh.list_installation_repositories(int(installation_id))
    except Exception as exc:
        raise HTTPException(502, f"Could not load repositories: {type(exc).__name__}")
    return {"repositories": repos}



@app.post("/review")
def review(body: ReviewIn, request: Request):
    try:
        owner, repo, number = gh.parse_pr_url(body.pr_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # Try public access first.
    try:
        diff = gh.fetch_diff(owner, repo, number)
        return run_review(diff)

    except gh.GitHubAccessError as first_error:
        session = _session(request)

        if not session:
            raise HTTPException(
                403,
                detail={
                    "code": "github_authorization_required",
                    "message": (
                        "This PR is private or inaccessible. "
                        "Sign in to ReviewPilot and connect a GitHub account "
                        "with access to this repository."
                    ),
                    "connect_url": "/auth/connect",
                },
            )

        # Only use installations explicitly connected to this session.
        candidates = _get_accessible_installations(session)

        for installation in candidates:
            try:
                token = gh.create_installation_token(
                    int(installation["id"])
                )
                diff = gh.fetch_diff(
                    owner,
                    repo,
                    number,
                    token=token,
                )
                return run_review(diff)

            except gh.GitHubAccessError:
                # This installation may not have access to this repository.
                continue

            except Exception:
                # Try the next connected installation.
                continue

        raise HTTPException(
            403,
            detail={
                "code": "github_installation_required",
                "message": (
                    "None of the GitHub App installations connected to this "
                    "ReviewPilot session could access this pull request. "
                    "Connect the correct installation or grant the GitHub "
                    "App access to the repository."
                ),
                "connect_url": "/auth/connect",
                "github_status": first_error.status_code,
            },
        )

    except Exception as exc:
        raise HTTPException(
            502,
            f"Review failed: {type(exc).__name__}",
        )


def review_and_comment(owner: str, repo: str, number: int, installation_id: int):
    token = gh.create_installation_token(installation_id)
    diff = gh.fetch_diff(owner, repo, number, token=token)
    result = run_review(diff)
    gh.post_comment(owner, repo, number, to_markdown(result), token=token)


@app.post("/webhook")
async def webhook(
    req: Request,
    tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    body = await req.body()
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret or not valid_signature(body, x_hub_signature_256, secret):
        raise HTTPException(401, "bad signature")
    if x_github_event != "pull_request":
        return {"skipped": x_github_event}

    payload = await req.json()
    if payload.get("action") not in ("opened", "synchronize"):
        return {"skipped": payload.get("action")}

    repo_data = payload.get("repository", {})
    owner, repo = (repo_data.get("full_name") or "/").split("/", 1)
    number = payload.get("pull_request", {}).get("number")
    installation_id = (payload.get("installation") or {}).get("id")
    if not number or not installation_id:
        return {"skipped": "missing_pull_request_or_installation"}
    tasks.add_task(review_and_comment, owner, repo, int(number), int(installation_id))
    return {"queued": number}
