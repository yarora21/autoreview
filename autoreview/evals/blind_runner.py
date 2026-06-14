"""
Blind eval runner — runs AutoReview on PRs without knowing their labels.

Combines bug + clean items into a single shuffled list, runs the agent,
and saves raw findings. Labels are stored separately and only joined
at metric computation time.

Usage:
    python -m autoreview.evals.blind_runner
        --bugs  autoreview/evals/dataset/bugsinpy_items.json
        --clean autoreview/evals/dataset/clean_items.json
        --out   autoreview/evals/dataset/blind_results.json
"""
from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()

from autoreview.core.github_client import get_pr
from autoreview.core.schemas import EvalItem
from autoreview.retrieval.context_pack import ContextPack

logger = logging.getLogger(__name__)


def run_pr(pr_url: str) -> list[dict]:
    """Run the multi-agent graph on a PR and return raw findings."""
    from autoreview.agents.graph import build_graph
    diff_chunks = get_pr(pr_url)
    context = ContextPack(diff_chunks=diff_chunks)
    graph = build_graph()
    state = graph.invoke({"context": context, "raw_findings": [], "findings": []})
    return [f.model_dump() for f in state["findings"]]


@click.command()
@click.option("--bugs", default="autoreview/evals/dataset/bugsinpy_items.json")
@click.option("--clean", default="autoreview/evals/dataset/clean_items.json")
@click.option("--out", default="autoreview/evals/dataset/blind_results.json")
@click.option("--limit", default=None, type=int, help="Only run first N items.")
@click.option("--seed", default=42, help="Random seed for shuffle.")
def main(bugs: str, clean: str, out: str, limit: int, seed: int):
    """Run blind eval — agent sees no labels."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    bug_items = [EvalItem(**i) for i in json.loads(Path(bugs).read_text())]
    clean_items = [EvalItem(**i) for i in json.loads(Path(clean).read_text())]
    all_items = bug_items + clean_items

    random.seed(seed)
    random.shuffle(all_items)

    if limit:
        all_items = all_items[:limit]

    results = []
    for i, item in enumerate(all_items):
        logger.info("[%d/%d] %s#%d", i + 1, len(all_items), item.repo, item.pr_number)
        try:
            findings = run_pr(item.pr_url)
        except Exception as e:
            logger.error("Failed %s: %s", item.pr_url, e)
            findings = []

        results.append({
            "pr_url": item.pr_url,
            "repo": item.repo,
            "pr_number": item.pr_number,
            "label": item.label,           # stored but not used by agent
            "bug_file": item.bug_file,
            "bug_start_line": item.bug_start_line,
            "bug_end_line": item.bug_end_line,
            "num_findings": len(findings),
            "findings": findings,
            "reviewed": [],                # filled in by review_cli.py
        })
        time.sleep(1)

    Path(out).write_text(json.dumps(results, indent=2))
    logger.info("Saved %d results to %s", len(results), out)
    logger.info("Bug PRs: %d  Clean PRs: %d  Total findings: %d",
                sum(1 for r in results if r["label"] == "bug"),
                sum(1 for r in results if r["label"] == "clean"),
                sum(r["num_findings"] for r in results))


if __name__ == "__main__":
    main()
