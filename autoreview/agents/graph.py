from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from autoreview.agents.base import run_agent
from autoreview.core.schemas import Finding
from autoreview.retrieval.context_pack import ContextPack

PROMPTS = Path(__file__).parent / "prompts"


# raw_findings accumulates across parallel agents via operator.add.
# findings is written once by the synthesizer (plain list, no reducer).
class ReviewState(TypedDict):
    context: ContextPack
    raw_findings: Annotated[list[Finding], operator.add]
    findings: list[Finding]


def bug_node(state: ReviewState) -> dict:
    return {"raw_findings": run_agent("bug", PROMPTS / "bug.txt", state["context"])}


def security_node(state: ReviewState) -> dict:
    return {"raw_findings": run_agent("security", PROMPTS / "security.txt", state["context"])}


def style_node(state: ReviewState) -> dict:
    return {"raw_findings": run_agent("style", PROMPTS / "style.txt", state["context"])}


def synthesizer_node(state: ReviewState) -> dict:
    from autoreview.agents.synthesizer import synthesize
    return {"findings": synthesize(state["raw_findings"])}


def build_graph():
    graph = StateGraph(ReviewState)

    graph.add_node("bug", bug_node)
    graph.add_node("security", security_node)
    graph.add_node("style", style_node)
    graph.add_node("synthesizer", synthesizer_node)

    # Fan out from START to all three agents in parallel
    graph.add_edge(START, "bug")
    graph.add_edge(START, "security")
    graph.add_edge(START, "style")

    # Fan in: all agents must complete before synthesizer runs
    graph.add_edge("bug", "synthesizer")
    graph.add_edge("security", "synthesizer")
    graph.add_edge("style", "synthesizer")

    graph.add_edge("synthesizer", END)

    return graph.compile()
