from fastapi.testclient import TestClient
from app import agent, main, gh


def test_graph_runs_all_nodes(monkeypatch):
    seen = []
    monkeypatch.setattr(agent, "llm", lambda s, u: seen.append(s) or f"out{len(seen)}")
    r = agent.run_review("diff --git a b")
    assert set(r) == {"plan", "review", "tests"} and len(seen) == 3


def test_secrets_never_reach_llm(monkeypatch):
    got = []
    monkeypatch.setattr(agent, "llm", lambda s, u: got.append(u) or "ok")
    agent.run_review("+ token = 'abcdef123456'")
    assert all("abcdef123456" not in u for u in got)


def test_parse_pr_url():
    assert gh.parse_pr_url("https://github.com/a/b/pull/12") == ("a", "b", 12)


def test_review_endpoint(monkeypatch):
    monkeypatch.setattr(main.gh, "fetch_diff", lambda *a: "d")
    monkeypatch.setattr(main, "run_review", lambda d: {"plan": "p", "review": "r", "tests": "t"})
    c = TestClient(main.app)
    assert c.post("/review", json={"pr_url": "https://github.com/a/b/pull/1"}).json()["review"] == "r"
    assert c.post("/review", json={"pr_url": "nope"}).status_code == 400