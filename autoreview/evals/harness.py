"""
Eval harness: run AutoReview against benchmark items and record results.

Usage:
    python -m autoreview.evals.harness --dataset autoreview/evals/dataset/items.json
                                       --out autoreview/evals/dataset/results.json
                                       [--single-agent] [--no-rag]
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

load_dotenv()

from autoreview.core.github_client import get_pr
from autoreview.core.schemas import EvalItem, Finding
from autoreview.retrieval.context_pack import ContextPack

logger = logging.getLogger(__name__)

# A finding "hits" if it's in the right file and within N lines of the labeled range
HIT_LINE_TOLERANCE = 10


def _is_hit(finding: Finding, item: EvalItem) -> bool:
    """Return True if the finding overlaps with the labeled bug location."""
    if not item.bug_file:
        return False
    if finding.file_path != item.bug_file and not finding.file_path.endswith(item.bug_file):
        return False
    start = (item.bug_start_line or 0) - HIT_LINE_TOLERANCE
    end = (item.bug_end_line or 0) + HIT_LINE_TOLERANCE
    return finding.start_line <= end and finding.end_line >= start


def run_item(item: EvalItem, single_agent: bool = False) -> dict:
    """Run AutoReview on one eval item and return a result record."""
    try:
        diff_chunks = get_pr(item.pr_url)
        context = ContextPack(diff_chunks=diff_chunks)

        if single_agent:
            from autoreview.agents.reviewer import review
            result = review(item.pr_url, context)
            findings = result.findings
        else:
            from autoreview.agents.graph import build_graph
            graph = build_graph()
            state = graph.invoke({"context": context, "findings": []})
            findings = state["findings"]

        hit = any(_is_hit(f, item) for f in findings) if item.label == "bug" else False

        return {
            "repo": item.repo,
            "pr_number": item.pr_number,
            "pr_url": item.pr_url,
            "label": item.label,
            "bug_file": item.bug_file,
            "num_findings": len(findings),
            "hit": hit,
            "false_positive": item.label == "clean" and len(findings) > 0,
            "findings": [f.model_dump() for f in findings],
        }

    except Exception as e:
        logger.error("Failed %s: %s", item.pr_url, e)
        return {
            "repo": item.repo,
            "pr_number": item.pr_number,
            "pr_url": item.pr_url,
            "label": item.label,
            "error": str(e),
            "hit": False,
            "false_positive": False,
            "num_findings": 0,
            "findings": [],
        }


@click.command()
@click.option("--dataset", default="autoreview/evals/dataset/items.json")
@click.option("--out", default="autoreview/evals/dataset/results.json")
@click.option("--single-agent", is_flag=True, help="Use single-agent mode.")
@click.option("--limit", default=None, type=int, help="Only run first N items (for smoke tests).")
def main(dataset: str, out: str, single_agent: bool, limit: Optional[int]):
    """Run AutoReview against the benchmark dataset."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    items = [EvalItem(**i) for i in json.loads(Path(dataset).read_text())]
    if limit:
        items = items[:limit]

    results = []
    for i, item in enumerate(items):
        logger.info("[%d/%d] %s#%d (%s)", i + 1, len(items), item.repo, item.pr_number, item.label)
        result = run_item(item, single_agent=single_agent)
        results.append(result)
        time.sleep(1)  # avoid hammering APIs

    Path(out).write_text(json.dumps(results, indent=2))
    logger.info("Saved %d results to %s", len(results), out)

    # Print quick summary
    from autoreview.evals.metrics import compute_metrics
    metrics = compute_metrics(results)
    print(f"\nPrecision: {metrics['precision']:.2f}  Recall: {metrics['recall']:.2f}  FPR: {metrics['fpr']:.2f}")
    print(f"Bugs: {metrics['total_bugs']}  Clean: {metrics['total_clean']}  Hits: {metrics['hits']}")


if __name__ == "__main__":
    main()
