import hmac, hashlib, json
from fastapi.testclient import TestClient
from app import main
from app.main import app, valid_signature

SECRET = "s3cret"
client = TestClient(app)


def sign(b: bytes, secret=SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), b, hashlib.sha256).hexdigest()


def pr(action="opened"):
    return json.dumps({"action": action, "pull_request": {"number": 7},
                       "repository": {"full_name": "me/repo"}}).encode()


def post(b, sig, event="pull_request"):
    return client.post("/webhook", content=b, headers={
        "X-Hub-Signature-256": sig, "X-GitHub-Event": event, "Content-Type": "application/json"})


def test_signature_valid_and_invalid():
    assert valid_signature(b"x", sign(b"x"), SECRET)
    assert not valid_signature(b"x", sign(b"x", "other"), SECRET)
    assert not valid_signature(b"x", "abc", SECRET)


def test_bad_signature_401(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    assert post(pr(), "sha256=bad").status_code == 401


def test_opened_pr_queued(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    calls = []
    monkeypatch.setattr(main, "review_and_comment", lambda *a: calls.append(a))
    b = pr()
    r = post(b, sign(b))
    assert r.json() == {"queued": 7} and calls == [("me", "repo", 7)]


def test_closed_pr_skipped(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    b = pr("closed")
    assert "skipped" in post(b, sign(b)).json()