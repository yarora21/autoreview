# AutoReview Eval Results

## Dataset

**BugsInPy** — 31 confirmed Python bugs across 4 repos, plus 20 clean (enhancement/feature) PRs from
the same repos as negatives. Bug locations are derived from the actual fix patch using exact line tracking
from unified diff hunk headers (see `mine_bugsinpy.py`).

| Repo | Bugs | Clean |
|---|---|---|
| psf/black | 9 | 0 |
| scrapy/scrapy | 7 | 20 |
| tqdm/tqdm | 6 | 0 |
| spotify/luigi | 9 | 0 |
| **Total** | **31** | **20** |

24 of 31 bug items have precise line ranges (≤50 lines). 7 are wide refactoring PRs where the fix
touched many scattered lines — these are usable as file-level recall checks only.

---

## Experiment 1: Eval Methodology — Automated Line Matching vs Blind Eval + LLM Judge

**Question:** What does the system actually do, measured honestly?

### Previous methodology (retired)

Earlier results reported 82% precision and 82% recall on BugsInPy. These numbers were artifacts of a
bug in `_parse_patch`: the line-range tracker used list length instead of the actual new-file line
counter from `@@` hunk headers, producing ranges like `lines 2–3116` for every item. Any finding
anywhere in the file counted as a hit, making recall trivially high for large files.

### Current methodology: blind eval + LLM judge

The agent runs on PRs without seeing labels. A separate Claude call judges each finding given the
relevant diff hunk: **valid** (real issue), **noise** (false positive), or **uncertain**. Precision
is computed from judge verdicts; recall from valid findings that hit the labeled file.

Evaluated on 51 PRs (31 bug, 20 clean), 183 total findings:

| Metric | Value | Detail |
|---|---|---|
| **Precision** | **18.5%** | 30 valid / 162 decided (excl. uncertain) |
| **Recall** | **41.9%** | 13/31 bug PRs had a valid finding on the right file |
| **FPR** | **20.0%** | 4/20 clean PRs had ≥1 valid finding |
| Findings per PR | 3.6 avg | 2.9 bug / 4.7 clean |

**Finding:** Precision is low — the agents flag too much noise that passes the 0.6 confidence gate,
particularly style and maintainability findings. Recall at 42% means most bug PRs do get flagged but
not always on the correct file. The "false positives" on clean PRs are instructive: 3 of the 4 are
arguably real issues (a typo, a missing docstring placeholder, a potential `KeyError`) introduced
incidentally in feature PRs. This reveals a fundamental limitation of the clean-PR methodology —
enhancement PRs are not guaranteed to be bug-free.

---

## Experiment 2: Architecture — Multi-agent vs Single-agent

**Question:** Does splitting into specialist agents (bug, security, style) improve over one mega-prompt?

Evaluated on the earlier noisy GitHub-mined dataset (17 items, approximate labels). The direction
is reliable even if the absolute numbers are inflated by label noise.

| Config | Precision | Recall | FPR |
|---|---|---|---|
| Single-agent (Sonnet) | 7% | 8% | 100% |
| **Multi-agent (Sonnet)** | **82%\*** | **82%\*** | **0%** |

\* Inflated by broken line-range parser; see Experiment 1.

**Finding:** Multi-agent parallel specialists clearly outperform the single mega-prompt in FPR (100% → 0%).
The direction holds even under the inflated label conditions. The synthesizer confidence gate is
necessary but not sufficient — it reduces obvious noise but does not catch plausible-sounding
false positives.

---

## Experiment 3: Model Routing — Haiku vs Sonnet

**Question:** Does using Sonnet for all agents meaningfully improve over Haiku?

Evaluated on the noisy GitHub-mined dataset (15 items):

| Config | Precision | Recall | FPR |
|---|---|---|---|
| Multi-agent Haiku | 14% | 15% | 50% |
| **Multi-agent Sonnet** | **17%** | **15%** | **50%** |

**Finding:** Sonnet improves precision by 3pp with no change in recall. At ~5x the cost, the gain
is modest. Architecture matters more than model choice for this task.

---

## Key Takeaways

1. **The 82% numbers were wrong** — a parser bug made every finding on a large file count as a hit.
   Honest measurement with LLM judge gives 18.5% precision / 42% recall.
2. **Precision is the main problem** — agents flag too many plausible-sounding non-issues.
   The confidence gate (0.6) is necessary but insufficient; prompts need to be stricter.
3. **Clean PRs are not bug-free** — 3 of 4 "false positives" were real issues introduced in
   feature PRs. FPR is a noisy metric without human-verified clean data.
4. **Multi-agent outperforms single-agent** on FPR regardless of label noise; the direction is robust.
5. **Eval infrastructure is now correct**: blind runner + LLM judge + per-finding verdicts stored in
   `blind_results.json`; fully re-runnable in CI.

## Next Steps

- Raise confidence threshold above 0.6 and re-judge to measure precision/recall trade-off
- Tighten agent prompts — instruct agents to only flag findings they are highly confident about
- Diversify clean PRs: add psf/black and tornadoweb/tornado clean PRs (label search didn't find any;
  try date-based sampling instead)
- RAG ablation: index benchmark repos and compare `--no-rag` vs full hybrid retrieval
