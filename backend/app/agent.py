import os
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from .redact import redact

MAX_DIFF = 12000


class State(TypedDict, total=False):
    diff: str
    plan: str
    review: str
    tests: str


def llm(system: str, user: str) -> str:
    from groq import Groq
    r = Groq(api_key=os.environ["GROQ_API_KEY"]).chat.completions.create(
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
    )
    return r.choices[0].message.content


def plan_node(s: State):
    return {"plan": llm("You are a senior engineer. Summarize what this diff changes and name the riskiest areas. Be brief.", s["diff"])}


def review_node(s: State):
    return {"review": llm(
        "Review the diff for bugs, security issues and maintainability. Cite file names. Be concise.",
        f"Plan:\n{s['plan']}\n\nDiff:\n{s['diff']}")}


def tests_node(s: State):
    return {"tests": llm(
        "Suggest concrete unit and integration test cases for this diff. Short bullet list.",
        f"Review:\n{s['review']}\n\nDiff:\n{s['diff']}")}


g = StateGraph(State)
g.add_node("plan", plan_node)
g.add_node("review", review_node)
g.add_node("tests", tests_node)
g.add_edge(START, "plan")
g.add_edge("plan", "review")
g.add_edge("review", "tests")
g.add_edge("tests", END)
graph = g.compile()


def run_review(diff: str) -> dict:
    out = graph.invoke({"diff": redact(diff)[:MAX_DIFF]})
    return {k: out[k] for k in ("plan", "review", "tests")}