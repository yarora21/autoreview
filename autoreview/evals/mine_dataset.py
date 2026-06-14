"""
Mine labeled benchmark PRs from open-source Python repos.

Strategy:
- Bug items:   merged PRs labeled "bug" or "bugfix" where the diff touches .py files
- Clean items: merged PRs labeled "enhancement" or "feature" with no bug label

Usage:
    python -m autoreview.evals.mine_dataset --out autoreview/evals/dataset/items.json
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import click
import httpx

from autoreview.core.schemas import EvalItem

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Well-maintained Python repos with consistent bug labeling
TARGET_REPOS = [
    "psf/requests",
    "pallets/flask",
    "encode/httpx",
    "pydantic/pydantic",
    "sqlalchemy/sqlalchemy",
    "pytest-dev/pytest",
    "celery/celery",
    "aio-libs/aiohttp",
]

BUG_LABELS = {"bug", "bugfix", "type: bug", "kind/bug", "bug fix", "fix", "regression", "defect"}
CLEAN_LABELS = {"enhancement", "feature", "documentation", "type: feature", "improvement", "docs"}


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get_pr_files(repo: str, pr_number: int) -> list[dict]:
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
    resp = httpx.get(url, headers=_headers(), timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def _find_bug_location(files: list[dict]) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """Return the file and approximate line range of the first .py file changed."""
    for f in files:
        if f["filename"].endswith(".py") and f.get("patch"):
            # Find the first added/changed line from the patch
            lines = [i + 1 for i, l in enumerate(f["patch"].splitlines()) if l.startswith("+") and not l.startswith("+++")]
            if lines:
                return f["filename"], lines[0], lines[-1]
    return None, None, None


def _search_prs(repo: str, label: str, max_results: int) -> list[dict]:
    """Use GitHub search API to find merged PRs with a specific label."""
    url = f"{GITHUB_API}/search/issues"
    query = f"repo:{repo} is:pr is:merged label:{label}"
    params = {"q": query, "per_page": min(max_results, 30), "sort": "updated"}
    resp = httpx.get(url, headers=_headers(), params=params, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.json().get("items", [])


def mine_repo(repo: str, max_bugs: int = 15, max_clean: int = 8) -> list[EvalItem]:
    items = []

    # Mine bug PRs
    for label in ["bug", "bugfix", "regression"]:
        if len([i for i in items if i.label == "bug"]) >= max_bugs:
            break
        try:
            prs = _search_prs(repo, label, max_bugs)
            time.sleep(2)  # respect search API rate limit (30 req/min)
        except Exception as e:
            logger.warning("Search failed for %s label=%s: %s", repo, label, e)
            continue

        for pr in prs:
            if len([i for i in items if i.label == "bug"]) >= max_bugs:
                break
            pr_number = pr["number"]
            pr_url = pr["html_url"]
            try:
                files = _get_pr_files(repo, pr_number)
                bug_file, start, end = _find_bug_location(files)
                if bug_file:
                    items.append(EvalItem(
                        repo=repo, pr_number=pr_number, pr_url=pr_url,
                        label="bug", bug_file=bug_file,
                        bug_start_line=start, bug_end_line=end,
                        category="bug",
                    ))
                    logger.info("Bug PR: %s#%d (%s)", repo, pr_number, bug_file)
                time.sleep(0.3)
            except Exception as e:
                logger.warning("Skipping %s#%d: %s", repo, pr_number, e)

    # Mine clean PRs
    for label in ["enhancement", "documentation"]:
        if len([i for i in items if i.label == "clean"]) >= max_clean:
            break
        try:
            prs = _search_prs(repo, label, max_clean)
            time.sleep(1)
        except Exception as e:
            logger.warning("Search failed for %s label=%s: %s", repo, label, e)
            continue

        for pr in prs:
            if len([i for i in items if i.label == "clean"]) >= max_clean:
                break
            items.append(EvalItem(
                repo=repo, pr_number=pr["number"],
                pr_url=pr["html_url"], label="clean",
            ))
            logger.info("Clean PR: %s#%d", repo, pr["number"])

    return items


@click.command()
@click.option("--out", default="autoreview/evals/dataset/items.json", help="Output path for dataset JSON.")
@click.option("--max-bugs", default=15, help="Max bug PRs per repo.")
@click.option("--max-clean", default=8, help="Max clean PRs per repo.")
def main(out: str, max_bugs: int, max_clean: int):
    """Mine labeled benchmark PRs from open-source Python repos."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    all_items: list[EvalItem] = []

    for repo in TARGET_REPOS:
        logger.info("Mining %s...", repo)
        items = mine_repo(repo, max_bugs=max_bugs, max_clean=max_clean)
        all_items.extend(items)
        logger.info("%s: %d items", repo, len(items))

    bugs = sum(1 for i in all_items if i.label == "bug")
    cleans = sum(1 for i in all_items if i.label == "clean")
    logger.info("Total: %d bugs, %d clean", bugs, cleans)

    with open(out, "w") as f:
        json.dump([i.model_dump() for i in all_items], f, indent=2)
    logger.info("Saved to %s", out)


if __name__ == "__main__":
    main()
