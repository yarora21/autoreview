"""
LLM judge for AutoReview findings.

For each finding in blind_results.json, fetches the PR diff, extracts the
relevant file's hunk, and asks Claude whether the finding is valid/noise/uncertain.
Verdicts are written back into blind_results.json so the run is resumable.

Usage:
    python -m autoreview.evals.judge
        --results autoreview/evals/dataset/blind_results.json
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import anthropic
import click
from dotenv import load_dotenv

load_dotenv()

from autoreview.core.github_client import fetch_pr_diff, parse_pr_url

logger = logging.getLogger(__name__)
client = anthropic.Anthropic()

JUDGE_TOOL = {
    "name": "verdict",
    "description": "Record whether this automated finding identifies a real issue.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["valid", "noise", "uncertain"],
                "description": (
                    "valid = real issue a developer should act on; "
                    "noise = false positive, not a real problem; "
                    "uncertain = cannot determine without more context"
                ),
            },
            "reason": {
                "type": "string",
                "description": "One sentence explaining the verdict.",
            },
        },
        "required": ["verdict", "reason"],
    },
}

SYSTEM_PROMPT = """You are a senior software engineer auditing findings from an automated code review tool.

For each finding you will see:
1. The finding metadata (category, severity, file, lines, description)
2. The diff hunk for that file from the pull request

Your job: decide if the finding identifies a REAL, ACTIONABLE issue.

Criteria:
- "valid"     — genuine bug, security flaw, or meaningful problem; a developer should address it
- "noise"     — false positive; the code is fine, the concern is inapplicable, or it is trivial nitpicking
- "uncertain" — you cannot judge validity without seeing more of the codebase (e.g. the finding refers to code not in the diff)

Be strict. Automated reviewers produce a lot of noise. Only mark "valid" if the issue is clearly real."""


def _extract_file_diff(diff_text: str, file_path: str) -> str:
    """Extract the diff section for a specific file from a full PR diff."""
    sections: list[str] = []
    current: list[str] = []
    in_target = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current and in_target:
                sections.append("\n".join(current))
            current = [line]
            # Match if file_path appears as a suffix of the b/ path
            in_target = line.endswith(file_path) or f"b/{file_path}" in line
        else:
            current.append(line)

    if current and in_target:
        sections.append("\n".join(current))

    return "\n".join(sections) if sections else ""


def judge_finding(finding: dict, diff_text: str) -> dict:
    """Call Claude to judge one finding. Returns {verdict, reason}."""
    file_diff = _extract_file_diff(diff_text, finding["file_path"])

    if not file_diff:
        # Finding refers to a file not in the diff — almost certainly noise
        return {
            "verdict": "noise",
            "reason": f"File '{finding['file_path']}' not found in the PR diff.",
        }

    finding_block = (
        f"Category: {finding['category']} / Severity: {finding['severity']}\n"
        f"File: {finding['file_path']} lines {finding['start_line']}–{finding['end_line']}\n"
        f"Confidence: {finding['confidence']:.0%}\n\n"
        f"Description: {finding['description']}\n"
    )
    if finding.get("suggested_fix"):
        finding_block += f"\nSuggested fix: {finding['suggested_fix']}"

    user_message = (
        f"## Finding\n\n{finding_block}\n\n"
        f"## Diff for `{finding['file_path']}`\n\n```diff\n{file_diff[:6000]}\n```\n\n"
        "Is this finding valid, noise, or uncertain?"
    )

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=SYSTEM_PROMPT,
        tools=[JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "verdict"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "verdict":
            return block.input

    return {"verdict": "uncertain", "reason": "Judge returned no tool call."}


def _compute_metrics(data: list[dict]) -> None:
    """Print precision, recall, and FPR from judged findings."""
    all_verdicts: list[str] = [
        f["judge_verdict"]
        for pr in data
        for f in pr["findings"]
        if "judge_verdict" in f
    ]

    if not all_verdicts:
        print("No judged findings yet.")
        return

    valid = all_verdicts.count("valid")
    noise = all_verdicts.count("noise")
    uncertain = all_verdicts.count("uncertain")
    decided = valid + noise

    print(f"\nFindings judged: {len(all_verdicts)}  "
          f"(valid={valid}, noise={noise}, uncertain={uncertain})")
    print(f"Precision (valid / decided): {valid/decided:.1%}" if decided else "Precision: n/a")

    # Recall: bug PRs where >=1 finding was judged valid, hitting labeled file
    bug_prs = [pr for pr in data if pr["label"] == "bug"]
    hits = 0
    for pr in bug_prs:
        bug_file = pr.get("bug_file", "")
        for f in pr["findings"]:
            if f.get("judge_verdict") == "valid" and (
                f["file_path"] == bug_file or f["file_path"].endswith(bug_file)
            ):
                hits += 1
                break
    recall = hits / len(bug_prs) if bug_prs else 0.0
    print(f"Recall  (bug PRs with valid hit): {recall:.1%}  ({hits}/{len(bug_prs)})")

    # FPR: clean PRs with at least one valid finding
    clean_prs = [pr for pr in data if pr["label"] == "clean"]
    fps = sum(
        1 for pr in clean_prs
        if any(f.get("judge_verdict") == "valid" for f in pr["findings"])
    )
    fpr = fps / len(clean_prs) if clean_prs else 0.0
    print(f"FPR     (clean PRs flagged valid): {fpr:.1%}  ({fps}/{len(clean_prs)})")


@click.command()
@click.option("--results", default="autoreview/evals/dataset/blind_results.json")
@click.option("--limit", default=None, type=int, help="Max findings to judge this run.")
def main(results: str, limit: int):
    """Run LLM judge over findings in blind_results.json."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    path = Path(results)
    data = json.loads(path.read_text())

    judged = 0
    for pr in data:
        findings_to_judge = [f for f in pr["findings"] if "judge_verdict" not in f]
        if not findings_to_judge:
            continue

        logger.info("Fetching diff for %s", pr["pr_url"])
        try:
            owner, repo, pr_num = parse_pr_url(pr["pr_url"])
            diff_text = fetch_pr_diff(owner, repo, pr_num)
            time.sleep(0.5)
        except Exception as e:
            logger.error("Failed to fetch diff for %s: %s", pr["pr_url"], e)
            continue

        for finding in findings_to_judge:
            if limit and judged >= limit:
                break
            try:
                result = judge_finding(finding, diff_text)
                finding["judge_verdict"] = result["verdict"]
                finding["judge_reason"] = result["reason"]
                logger.info(
                    "  [%s] %s:%s-%s — %s",
                    result["verdict"].upper(),
                    finding["file_path"],
                    finding["start_line"],
                    finding["end_line"],
                    result["reason"][:80],
                )
                judged += 1
            except Exception as e:
                logger.error("Judge failed for finding: %s", e)
                finding["judge_verdict"] = "uncertain"
                finding["judge_reason"] = f"Judge error: {e}"
                judged += 1

        path.write_text(json.dumps(data, indent=2))

        if limit and judged >= limit:
            break

    logger.info("Judged %d findings total.", judged)
    _compute_metrics(data)


if __name__ == "__main__":
    main()
