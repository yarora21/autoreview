"""
Mine labeled benchmark items from BugsInPy.

Each BugsInPy entry has:
  - bug.info:      buggy_commit_id, fixed_commit_id
  - bug_patch.txt: the diff that fixed the bug (ground truth file + lines)
  - project.info:  github_url

We find the GitHub PR that introduced the fix commit, then construct an EvalItem
with the exact bug location from the patch.

Usage:
    python -m autoreview.evals.mine_bugsinpy --out autoreview/evals/dataset/bugsinpy_items.json
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path

import click
import httpx

from autoreview.core.schemas import EvalItem

logger = logging.getLogger(__name__)

BUGSINPY_API = "https://api.github.com/repos/soarsmu/BugsInPy/contents/projects"

# Projects to mine — well-known Python libs with clean patch history
TARGET_PROJECTS = ["black", "scrapy", "tornado", "tqdm", "luigi", "PySnooper", "spacy"]


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _get_file(path: str) -> str:
    """Fetch and decode a file from the BugsInPy GitHub repo."""
    resp = httpx.get(
        f"https://api.github.com/repos/soarsmu/BugsInPy/contents/{path}",
        headers=_headers(), timeout=15, follow_redirects=True,
    )
    resp.raise_for_status()
    return base64.b64decode(resp.json()["content"]).decode()


def _parse_info(text: str) -> dict:
    """Parse key="value" format from .info files."""
    return dict(re.findall(r'(\w+)="([^"]*)"', text))


def _parse_patch(patch: str) -> tuple[str | None, int, int]:
    """Extract the first changed .py file and its line range from a unified diff.

    Tracks the new-file line counter from each @@ hunk header so we get the
    actual line numbers in the fixed file, not list-position offsets.
    """
    current_file = None
    changed_lines: list[int] = []
    current_line = 0

    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            fname = line[6:].strip()
            if fname.endswith(".py"):
                if not current_file:
                    current_file = fname
                elif current_file != fname:
                    break  # stop at the second .py file; first is the bug location
        elif line.startswith("@@ "):
            m = re.search(r"\+(\d+)", line)
            if m:
                current_line = int(m.group(1))
        elif current_file:
            if line.startswith("+") and not line.startswith("+++"):
                changed_lines.append(current_line)
                current_line += 1
            elif line.startswith("-"):
                pass  # deleted line — no new-file line number
            elif not line.startswith("\\"):  # skip "\ No newline at end of file"
                current_line += 1  # context line

    if not current_file or not changed_lines:
        return None, 0, 0
    return current_file, min(changed_lines), max(changed_lines)


def _find_pr_for_commit(repo: str, commit_sha: str) -> str | None:
    """Find the PR URL that contains this commit, using GitHub API."""
    url = f"https://api.github.com/repos/{repo}/commits/{commit_sha}/pulls"
    resp = httpx.get(
        url, headers={**_headers(), "Accept": "application/vnd.github.v3+json"},
        timeout=15, follow_redirects=True,
    )
    if resp.status_code != 200:
        return None
    prs = resp.json()
    return prs[0]["html_url"] if prs else None


def mine_project(project: str, max_bugs: int = 10) -> list[EvalItem]:
    # Get list of bug IDs
    resp = httpx.get(
        f"{BUGSINPY_API}/{project}/bugs",
        headers=_headers(), timeout=15, follow_redirects=True,
    )
    if resp.status_code in (404, 403):
        logger.warning("Project %s: %s", project, resp.status_code)
        return []
    resp.raise_for_status()
    bug_ids = [e["name"] for e in resp.json() if e["type"] == "dir"]

    # Get repo slug from project.info
    proj_info = _parse_info(_get_file(f"projects/{project}/project.info"))
    github_url = proj_info.get("github_url", "").rstrip("/")
    repo = "/".join(github_url.split("/")[-2:])  # e.g. "psf/black"

    items = []
    for bug_id in sorted(bug_ids, key=int)[:max_bugs]:
        try:
            bug_info = _parse_info(_get_file(f"projects/{project}/bugs/{bug_id}/bug.info"))
            patch = _get_file(f"projects/{project}/bugs/{bug_id}/bug_patch.txt")

            fixed_sha = bug_info.get("fixed_commit_id", "")
            bug_file, start_line, end_line = _parse_patch(patch)

            if not bug_file or not fixed_sha:
                logger.warning("Skipping %s/%s: missing file or commit", project, bug_id)
                continue

            pr_url = _find_pr_for_commit(repo, fixed_sha)
            if not pr_url:
                logger.warning("No PR found for %s/%s (commit %s)", project, bug_id, fixed_sha[:8])
                continue

            pr_number = int(pr_url.rstrip("/").split("/")[-1])
            items.append(EvalItem(
                repo=repo,
                pr_number=pr_number,
                pr_url=pr_url,
                label="bug",
                bug_file=bug_file,
                bug_start_line=start_line,
                bug_end_line=end_line,
                category="bug",
            ))
            logger.info("Found: %s bug %s → %s (%s lines %d-%d)",
                        project, bug_id, pr_url, bug_file, start_line, end_line)
            time.sleep(0.5)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Skipping %s/%s: not found", project, bug_id)
            else:
                logger.warning("Failed %s/%s: %s", project, bug_id, e)
            time.sleep(0.5)
        except Exception as e:
            logger.warning("Failed %s/%s: %s", project, bug_id, e)
            time.sleep(0.5)

    return items


@click.command()
@click.option("--out", default="autoreview/evals/dataset/bugsinpy_items.json")
@click.option("--max-bugs", default=10, help="Max bugs per project.")
def main(out: str, max_bugs: int):
    """Mine BugsInPy into EvalItems."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    all_items: list[EvalItem] = []
    for project in TARGET_PROJECTS:
        logger.info("Mining %s...", project)
        items = mine_project(project, max_bugs=max_bugs)
        logger.info("%s: %d items", project, len(items))
        all_items.extend(items)
        # Save after each project so progress isn't lost on rate limit errors
        with open(out, "w") as f:
            json.dump([i.model_dump() for i in all_items], f, indent=2)
        time.sleep(2)

    logger.info("Total: %d items — saved to %s", len(all_items), out)


if __name__ == "__main__":
    main()
