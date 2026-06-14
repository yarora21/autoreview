from __future__ import annotations


def compute_metrics(results: list[dict]) -> dict:
    """
    Compute precision, recall, and false positive rate from harness results.

    Definitions:
    - hit:            bug PR where at least one finding matched the labeled location
    - miss:           bug PR where no finding matched
    - false positive: clean PR where AutoReview reported at least one finding
    - true negative:  clean PR where AutoReview reported nothing
    """
    bug_results   = [r for r in results if r["label"] == "bug" and "error" not in r]
    clean_results = [r for r in results if r["label"] == "clean" and "error" not in r]

    hits           = sum(1 for r in bug_results if r["hit"])
    misses         = len(bug_results) - hits
    false_positives = sum(1 for r in clean_results if r["false_positive"])
    true_negatives  = len(clean_results) - false_positives

    # Precision: of all PRs where we reported findings, how many actually had bugs?
    # (measured at PR level, not individual finding level)
    prs_with_findings = sum(1 for r in results if r["num_findings"] > 0 and "error" not in r)
    precision = hits / prs_with_findings if prs_with_findings > 0 else 0.0

    # Recall: of all bug PRs, how many did we catch?
    recall = hits / len(bug_results) if bug_results else 0.0

    # False positive rate: of all clean PRs, how many did we wrongly flag?
    fpr = false_positives / len(clean_results) if clean_results else 0.0

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "fpr": round(fpr, 3),
        "hits": hits,
        "misses": misses,
        "false_positives": false_positives,
        "true_negatives": true_negatives,
        "total_bugs": len(bug_results),
        "total_clean": len(clean_results),
        "errors": len([r for r in results if "error" in r]),
    }


def print_report(results: list[dict], label: str = "") -> None:
    """Print a formatted metrics report."""
    m = compute_metrics(results)
    header = f"=== {label} ===" if label else "=== Results ==="
    print(f"\n{header}")
    print(f"Precision:          {m['precision']:.1%}")
    print(f"Recall:             {m['recall']:.1%}")
    print(f"False positive rate:{m['fpr']:.1%}")
    print(f"Hits / Bug PRs:     {m['hits']} / {m['total_bugs']}")
    print(f"FPs / Clean PRs:    {m['false_positives']} / {m['total_clean']}")
    if m["errors"]:
        print(f"Errors:             {m['errors']}")
