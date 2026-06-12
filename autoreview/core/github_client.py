from __future__ import annotations

import re
import os
import httpx
from autoreview.core.schemas import DiffChunk

GITHUB_API = "https://api.github.com"
PR_URL_PATTERN = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    match = PR_URL_PATTERN.search(pr_url)
    if not match:
        raise ValueError(f"Invalid PR URL: {pr_url}")
    return match.group(1), match.group(2), int(match.group(3))


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError("GITHUB_TOKEN environment variable is required")
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}


def fetch_pr_diff(owner: str, repo: str, pr_number: int) -> str:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = {**_headers(), "Accept": "application/vnd.github.v3.diff"}
    resp = httpx.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_diff(diff_text: str) -> list[DiffChunk]:
    chunks = []
    current_file = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            # extract b/path
            parts = line.split(" b/")
            current_file = parts[-1] if len(parts) > 1 else None

        elif line.startswith("@@") and current_file:
            # @@ -old_start,old_count +new_start,new_count @@
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2) or "1")
                chunks.append(DiffChunk(
                    file_path=current_file,
                    start_line=start,
                    end_line=start + count - 1,
                    content="",
                ))

        elif chunks and not line.startswith("diff --git"):
            chunks[-1].content += line + "\n"

    return chunks


def get_pr(pr_url: str) -> list[DiffChunk]:
    owner, repo, pr_number = parse_pr_url(pr_url)
    diff_text = fetch_pr_diff(owner, repo, pr_number)
    return parse_diff(diff_text)
