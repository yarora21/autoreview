from __future__ import annotations

from autoreview.core.schemas import Finding, Severity

CONFIDENCE_THRESHOLD = 0.6

SEVERITY_RANK = {
    Severity.critical: 0,
    Severity.high: 1,
    Severity.medium: 2,
    Severity.low: 3,
    Severity.info: 4,
}


def synthesize(findings: list[Finding]) -> list[Finding]:
    """Dedupe, confidence-gate, and rank findings from all agents."""

    # Drop low-confidence findings
    findings = [f for f in findings if f.confidence >= CONFIDENCE_THRESHOLD]

    # Dedupe: if two findings share the same file + overlapping lines + category, keep the higher-confidence one
    deduped: dict[str, Finding] = {}
    for f in findings:
        key = (f.file_path, f.category, f.start_line // 5)  # bucket by 5-line windows
        if key not in deduped or f.confidence > deduped[key].confidence:
            deduped[key] = f

    # Sort by severity then confidence
    return sorted(deduped.values(), key=lambda f: (SEVERITY_RANK[f.severity], -f.confidence))
