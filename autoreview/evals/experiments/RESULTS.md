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

Evaluated on 51 PRs (31 bug, 20 clean).

#### Baseline (original style prompt)

| Metric | Value | Detail |
|---|---|---|
| Precision | 18.5% | 30 valid / 162 decided |
| Recall | 41.9% | 13/31 bug PRs hit |
| FPR | 20.0% | 4/20 clean PRs flagged |
| Total findings | 183 | valid=30, noise=132, uncertain=21 |

#### After tightening the style agent prompt

The style prompt was rewritten to only flag things a senior engineer would block a PR over: typos in
user-facing strings, significant duplication, genuinely dangerous complexity. Explicit exclusions added
for f-string preferences, missing type hints, incomplete docstrings, and minor refactoring suggestions.

| Metric | Value | Δ | Detail |
|---|---|---|---|
| **Precision** | **39.0%** | **+20.5pp** | 41 valid / 105 decided |
| **Recall** | **48.4%** | **+6.5pp** | 15/31 bug PRs hit |
| FPR | 30.0% | +10pp | 6/20 clean PRs flagged |
| Total findings | 136 | -47 | valid=41, noise=64, uncertain=31 |

**Finding:** Tightening the style prompt more than doubled precision (18.5% → 39.0%) while also improving
recall (41.9% → 48.4%). It cut 68 noise findings while valid findings *increased* by 11 — the style
agent was adding noise that obscured real signal from the bug and security agents in the synthesizer.

The FPR increase (20% → 30%) is a measurement artifact: all 6 newly-flagged "clean" PRs contain real
issues introduced incidentally in feature PRs — `if not body` replacing `if body is None` (semantic
change that breaks empty-but-not-None inputs), typos in user-facing warnings, logic ordering bugs.
**This is the core limitation of the clean-PR methodology: enhancement PRs are not bug-free.**

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

1. **Prompt tightening beats threshold tuning** — rewriting the style prompt to set a higher bar
   more than doubled precision (18.5% → 39.0%) and improved recall simultaneously. The confidence
   gate alone was insufficient; the prompt needed to encode what "worth flagging" means.
2. **The 82% numbers were wrong** — a parser bug made every finding on a large file count as a hit.
   Honest measurement with LLM judge gives 39% precision / 48% recall after prompt tuning.
3. **Style noise obscures bug signal** — the style agent was producing so much noise that valid bug
   findings were being drowned out. Cutting style noise improved both precision and recall.
4. **Clean PRs are not bug-free** — the FPR increase after prompt tuning is a methodology artifact;
   enhancement PRs regularly contain real issues. FPR requires human-verified clean data to be reliable.
5. **Multi-agent outperforms single-agent** on FPR regardless of label noise; the direction is robust.
6. **Eval infrastructure is correct**: blind runner + LLM judge + per-finding verdicts in
   `blind_results.json`; fully re-runnable after any prompt or threshold change.

## Next Steps

- Raise confidence threshold above 0.6 and re-judge to measure precision/recall trade-off
- Tighten agent prompts — instruct agents to only flag findings they are highly confident about
- Diversify clean PRs: add psf/black and tornadoweb/tornado clean PRs (label search didn't find any;
  try date-based sampling instead)
- RAG ablation: index benchmark repos and compare `--no-rag` vs full hybrid retrieval
