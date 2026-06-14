"""
Human review CLI for blind eval findings.

Loads blind_results.json, shows each unreviewed finding with its PR context,
and lets you mark it valid / noise / uncertain.

Usage:
    python -m autoreview.evals.review_cli
        --results autoreview/evals/dataset/blind_results.json
"""
from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def _show_finding(pr_result: dict, finding: dict, idx: int, total: int):
    console.clear()
    console.print(f"\n[bold]Finding {idx}/{total}[/bold]")
    console.print(f"PR:   {pr_result['pr_url']}")
    console.print(f"Repo: {pr_result['repo']}  (label hidden during review)")
    console.print()

    panel_text = Text()
    panel_text.append(f"Agent:       {finding['category'].upper()} / {finding['severity'].upper()}\n", style="bold")
    panel_text.append(f"File:        {finding['file_path']}\n")
    panel_text.append(f"Lines:       {finding['start_line']}–{finding['end_line']}\n")
    panel_text.append(f"Confidence:  {finding['confidence']:.0%}\n\n")
    panel_text.append(f"{finding['description']}\n", style="yellow")
    if finding.get("suggested_fix"):
        panel_text.append(f"\nSuggested fix: {finding['suggested_fix']}", style="dim")

    console.print(Panel(panel_text, title="Finding", border_style="blue"))
    console.print()
    console.print("  [bold green][v][/bold green] valid     — real issue worth flagging")
    console.print("  [bold red][n][/bold red] noise     — false positive, not a real issue")
    console.print("  [bold yellow][u][/bold yellow] uncertain — can't tell without more context")
    console.print("  [bold dim][s][/bold dim] skip      — skip for now")
    console.print("  [bold dim][q][/bold dim] quit      — save and exit")
    console.print()


def _prompt_choice() -> str:
    while True:
        choice = input("Your review: ").strip().lower()
        if choice in ("v", "n", "u", "s", "q"):
            return choice
        console.print("[red]Enter v, n, u, s, or q[/red]")


@click.command()
@click.option("--results", default="autoreview/evals/dataset/blind_results.json")
def main(results: str):
    """Human review interface for blind eval findings."""
    path = Path(results)
    data = json.loads(path.read_text())

    # Count total unreviewed findings
    all_findings = [
        (pr_idx, f_idx, pr, f)
        for pr_idx, pr in enumerate(data)
        for f_idx, f in enumerate(pr["findings"])
        if f_idx >= len(pr.get("reviewed", []))
    ]

    if not all_findings:
        console.print("[green]All findings have been reviewed![/green]")
        return

    console.print(f"[bold]{len(all_findings)} unreviewed findings[/bold] across {len(data)} PRs")
    console.print("Press Enter to start...")
    input()

    reviewed_count = 0
    for i, (pr_idx, f_idx, pr, finding) in enumerate(all_findings):
        _show_finding(pr, finding, i + 1, len(all_findings))
        choice = _prompt_choice()

        if choice == "q":
            console.print("\n[yellow]Saving and exiting...[/yellow]")
            break
        elif choice == "s":
            continue
        else:
            label_map = {"v": "valid", "n": "noise", "u": "uncertain"}
            if "reviewed" not in data[pr_idx]:
                data[pr_idx]["reviewed"] = []
            data[pr_idx]["reviewed"].append({
                "finding_idx": f_idx,
                "verdict": label_map[choice],
            })
            reviewed_count += 1

    path.write_text(json.dumps(data, indent=2))
    console.print(f"\n[green]Saved. Reviewed {reviewed_count} findings.[/green]")

    # Print quick stats on what's been reviewed so far
    verdicts = [
        r["verdict"]
        for pr in data
        for r in pr.get("reviewed", [])
    ]
    if verdicts:
        valid = verdicts.count("valid")
        noise = verdicts.count("noise")
        uncertain = verdicts.count("uncertain")
        total = len(verdicts)
        console.print(f"\nSo far: {valid} valid ({valid/total:.0%})  {noise} noise ({noise/total:.0%})  {uncertain} uncertain")


if __name__ == "__main__":
    main()
