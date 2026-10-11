
from fastapi.testclient import TestClient

from app import agent, main, gh


SAMPLE_DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 def get_role(user):
+    return user["role"]
     pass
"""


README_DIFF = """diff --git a/README.md b/README.md
new file mode 100644
--- /dev/null
+++ b/README.md
@@ -0,0 +1 @@
+test github pull changes analysis..
"""


def test_graph_runs_all_nodes(monkeypatch):
    seen = []

    monkeypatch.setattr(
        agent,
        "llm",
        lambda system, user: seen.append(system) or f"out{len(seen)}",
    )

    result = agent.run_review("diff --git a/app.py b/app.py")

    assert set(result) == {"plan", "review", "tests", "findings"}
    assert len(seen) == 3
    assert isinstance(result["findings"], list)


def test_secrets_never_reach_llm(monkeypatch):
    received_prompts = []

    monkeypatch.setattr(
        agent,
        "llm",
        lambda system, user: received_prompts.append(user) or "ok",
    )

    agent.run_review("+ token = 'abcdef123456'")

    assert received_prompts
    assert all(
        "abcdef123456" not in prompt
        for prompt in received_prompts
    )


def test_parse_pr_url():
    assert gh.parse_pr_url(
        "https://github.com/a/b/pull/12"
    ) == ("a", "b", 12)


def test_validate_finding_with_exact_evidence():
    finding = {
        "severity": "high",
        "file": "app.py",
        "line": 2,
        "title": "Missing role handling",
        "description": "The function assumes the role key exists.",
        "failure_scenario": (
            "A user dictionary without the role key raises KeyError."
        ),
        "evidence": 'user["role"]',
        "suggested_fix": "Validate the key or handle its absence.",
    }

    validated = agent.validate_findings([finding], SAMPLE_DIFF)

    assert len(validated) == 1
    assert validated[0]["file"] == "app.py"
    assert validated[0]["line"] == 2


def test_validate_finding_rejects_wrong_line():
    finding = {
        "severity": "high",
        "file": "app.py",
        "line": 999,
        "title": "Potential bug",
        "description": "Example description.",
        "failure_scenario": "Example failure scenario.",
        "evidence": 'user["role"]',
        "suggested_fix": "Validate the key.",
    }

    assert agent.validate_findings([finding], SAMPLE_DIFF) == []


def test_validate_finding_rejects_invented_evidence():
    finding = {
        "severity": "high",
        "file": "app.py",
        "line": 2,
        "title": "Potential bug",
        "description": "Example description.",
        "failure_scenario": "Example failure scenario.",
        "evidence": "this code does not exist",
        "suggested_fix": "Validate the key.",
    }

    assert agent.validate_findings([finding], SAMPLE_DIFF) == []


def test_validate_finding_rejects_unknown_file():
    finding = {
        "severity": "high",
        "file": "missing.py",
        "line": 2,
        "title": "Potential bug",
        "description": "Example description.",
        "failure_scenario": "Example failure scenario.",
        "evidence": 'user["role"]',
        "suggested_fix": "Validate the key.",
    }

    assert agent.validate_findings([finding], SAMPLE_DIFF) == []


def test_review_endpoint(monkeypatch):
    monkeypatch.setattr(
        main.gh,
        "fetch_diff",
        lambda *args, **kwargs: "d",
    )

    monkeypatch.setattr(
        main,
        "run_review",
        lambda diff: {
            "plan": "p",
            "review": "r",
            "tests": "t",
            "findings": [],
        },
    )

    client = TestClient(main.app)

    response = client.post(
        "/review",
        json={"pr_url": "https://github.com/a/b/pull/1"},
    )

    assert response.status_code == 200
    assert response.json()["review"] == "r"
    assert response.json()["findings"] == []

    invalid_response = client.post(
        "/review",
        json={"pr_url": "nope"},
    )

    assert invalid_response.status_code == 400


def test_readme_change_is_documentation_only():
    assert agent.is_documentation_only(README_DIFF)


def test_mixed_readme_and_python_change_is_not_docs_only():
    diff = README_DIFF + """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old_value = 1
+new_value = 2
"""

    assert not agent.is_documentation_only(diff)


def test_readme_plan_does_not_call_llm(monkeypatch):
    def unexpected_llm(*args, **kwargs):
        raise AssertionError(
            "Documentation-only summary should not call the LLM"
        )

    monkeypatch.setattr(agent, "llm", unexpected_llm)

    result = agent.plan_node({"diff": README_DIFF})

    assert "README.md" in result["plan"]
    assert "Documentation-only" in result["plan"]


def test_readme_review_returns_no_bug_findings(monkeypatch):
    def unexpected_llm(*args, **kwargs):
        raise AssertionError(
            "Documentation-only review should not call the LLM"
        )

    monkeypatch.setattr(agent, "llm", unexpected_llm)

    result = agent.review_node({
        "diff": README_DIFF,
        "plan": "Documentation-only change.",
    })

    assert result["findings"] == []
    assert "No actionable software bugs" in result["review"]


def test_readme_suggests_no_unnecessary_automated_tests(monkeypatch):
    def unexpected_llm(*args, **kwargs):
        raise AssertionError(
            "Documentation-only test suggestions should not call the LLM"
        )

    monkeypatch.setattr(agent, "llm", unexpected_llm)

    result = agent.tests_node({
        "diff": README_DIFF,
        "review": "No actionable software bugs.",
    })

    assert "No dedicated automated tests" in result["tests"]
