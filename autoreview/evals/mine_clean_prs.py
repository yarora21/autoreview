"""
Mine clean PRs from the same repos as BugsInPy bug items.

"Clean" = merged PRs labeled enhancement, documentation, or feature —
no bug label, no fix in the title. These are the negatives for the blind eval.

Usage:
    python -m autoreview.evals.mine_clean_prs --out autoreview/evals/dataset/clean_items.json
"""
from __future__ import annotations

import json
import logging
import os
import time

import click
import httpx

from autoreview.core.schemas import EvalItem

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Same repos as BugsInPy so distribution is similar
TARGET_REPOS = [
    "psf/black",
    "scrapy/scrapy",
    "tornadoweb/tornado",
]

CLEAN_LABELS = ["enhancement", "documentation", "feature"]
BUG_SIGNALS = {"bug", "bugfix", "fix", "regression", "defect"}


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _search_prs(repo: str, label: str, max_results: int) -> list[dict]:
    url = f"{GITHUB_API}/search/issues"
    query = f"repo:{repo} is:pr is:merged label:{label}"
    params = {"q": query, "per_page": min(max_results, 30), "sort": "updated"}
    resp = httpx.get(url, headers=_headers(), params=params, timeout=30, follow_redirects=True)
    if resp.status_code == 403:
        logger.warning("Rate limited on search")
        return []
    resp.raise_for_status()
    return resp.json().get("items", [])


def mine_clean_prs(repo: str, max_clean: int = 20) -> list[EvalItem]:
    items = []

    for label in CLEAN_LABELS:
        if len(items) >= max_clean:
            break
        try:
            prs = _search_prs(repo, label, max_clean)
            time.sleep(2)
        except Exception as e:
            logger.warning("Search failed %s label=%s: %s", repo, label, e)
            continue

        for pr in prs:
            if len(items) >= max_clean:
                break

            # Skip if PR has any bug-related labels
            pr_labels = {l["name"].lower() for l in pr.get("labels", [])}
            if pr_labels & BUG_SIGNALS:
                continue

            # Skip if title suggests a bug fix
            title = pr.get("title", "").lower()
            if any(w in title for w in ["fix", "bug", "crash", "error", "broken"]):
                continue

            pr_number = pr["number"]
            items.append(EvalItem(
                repo=repo,
                pr_number=pr_number,
                pr_url=pr["html_url"],
                label="clean",
            ))
            logger.info("Clean PR: %s#%d — %s", repo, pr_number, pr.get("title", "")[:60])

    return items


@click.command()
@click.option("--out", default="autoreview/evals/dataset/clean_items.json")
@click.option("--max-per-repo", default=20, help="Max clean PRs per repo.")
def main(out: str, max_per_repo: int):
    """Mine clean PRs for blind eval negatives."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    all_items: list[EvalItem] = []
    for repo in TARGET_REPOS:
        logger.info("Mining clean PRs from %s...", repo)
        items = mine_clean_prs(repo, max_clean=max_per_repo)
        logger.info("%s: %d clean PRs", repo, len(items))
        all_items.extend(items)
        time.sleep(2)

    logger.info("Total: %d clean PRs", len(all_items))
    with open(out, "w") as f:
        json.dump([i.model_dump() for i in all_items], f, indent=2)
    logger.info("Saved to %s", out)


if __name__ == "__main__":
    main()
