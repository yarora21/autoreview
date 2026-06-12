# AutoReview — Project Specification

An autonomous, multi-agent GitHub PR review system with RAG over the codebase and a rigorous eval harness. Built as a portfolio project for applied AI engineer roles — every architectural decision must be defensible with data.

**Owner context:** Solo developer, Python-strong, AWS-comfortable. Optimize for learning depth and interview-ready talking points over feature breadth. When there's a tradeoff between "more features" and "measurable quality," choose measurable quality.

---

## Product summary

AutoReview reviews GitHub pull requests automatically. Given a PR, it:

1. Fetches the diff and identifies changed functions/classes
2. Retrieves relevant context from a pre-built index of the repo (hybrid RAG: vector similarity + call-graph traversal)
3. Fans out to three parallel sub-agents (bug, security, style), each receiving a structured "context pack"
4. Synthesizes findings: dedupes, confidence-gates, ranks by severity
5. Posts a structured review with inline comments via the GitHub API

It ships with a labeled benchmark dataset and an eval harness that runs in CI. The README leads with eval results, not features.

---

## Tech stack

- **Language:** Python 3.11+
- **Agent orchestration:** LangGraph (state graph, parallel fan-out/fan-in)
- **LLM:** Anthropic API (Sonnet for bug/security agents, Haiku for style — subject to experiment results)
- **Schemas:** Pydantic v2 for all agent inputs/outputs
- **AST parsing:** tree-sitter (start with Python grammar; design for multi-language later)
- **Vector store:** Chroma (local, persistent)
- **Embeddings:** start with a hosted embedding API; abstract behind an interface so models can be swapped and compared
- **API server:** FastAPI
- **Queue:** start with a simple SQLite/Postgres-backed job table or Redis; keep the worker interface clean
- **Eval tracking:** Braintrust or Langfuse (pick one early, log all traces)
- **Frontend (phase 6):** minimal — Next.js or plain HTML+SSE for the agent trace view

## Repo layout

```
autoreview/
  core/
    schemas.py          # All Pydantic models (Finding, ContextPack, ReviewResult, ...)
    github_client.py    # PR fetch, diff parse, review posting
    config.py           # Model routing, thresholds, API keys via env
  indexing/
    chunker.py          # tree-sitter AST chunking
    embedder.py         # Embedding interface + implementations
    vector_store.py     # Chroma wrapper
    structural.py       # Call graph + import index
    pipeline.py         # Orchestrates full index build for a repo
  retrieval/
    retriever.py        # Hybrid retrieval: vector + graph, merge + rank
    context_pack.py     # Assembles diff + retrieved context within token budget
  agents/
    graph.py            # LangGraph state graph definition
    bug_agent.py
    security_agent.py
    style_agent.py
    synthesizer.py      # Dedupe, confidence gate, severity ranking
    prompts/            # One file per agent system prompt (versioned, eval-tested)
  evals/
    dataset/            # Benchmark PRs (metadata + labels, not full repos)
    mine_dataset.py     # Scripts to mine labeled PRs from open-source repos
    harness.py          # Run AutoReview against benchmark, compute metrics
    metrics.py          # Precision, recall, FPR, severity calibration
    experiments/        # Ablation configs + results
  server/
    app.py              # FastAPI: webhook endpoint, job enqueue
    worker.py           # Job consumer, runs the review pipeline
  cli.py                # `autoreview review <pr_url>` — primary interface until phase 6
  tests/
```

---

## Implementation phases

Work through these in order. Each phase must end with a working, demoable increment. Do not start a phase until the previous one's exit criteria are met.

### Phase 1 — Single-agent foundation (~3 days)

**Goal:** One end-to-end review with structured output. No orchestration, no RAG.

Tasks:
- [ ] `schemas.py`: define `Finding` (category, severity enum, file, line range, description, suggested_fix, confidence 0–1), `ReviewResult`, `DiffHunk`
- [ ] `github_client.py`: fetch PR metadata + unified diff given a PR URL (use a PAT for now); parse diff into `DiffHunk` objects with file paths and line numbers
- [ ] Single review agent: send diff to Claude with tool-use/structured-output enforcement so the response is a list of `Finding` objects — never free text
- [ ] `cli.py`: `autoreview review <pr_url>` prints findings as a table
- [ ] Basic error handling: API retries with exponential backoff, timeout
- [ ] Log every LLM call: prompt, response, tokens, latency, cost

Exit criteria: run the CLI against 3 real PRs, get typed findings with correct file/line anchors.

Key learning targets: tool use / structured outputs, prompt design for code analysis, diff parsing.

### Phase 2 — RAG: repo indexing pipeline (~5 days)

**Goal:** A standalone pipeline that turns a cloned repo into a searchable index. Independent of the review agent.

Tasks:
- [ ] `chunker.py`: tree-sitter parses each `.py` file into function/class-level chunks; each chunk carries metadata (file path, qualified name, docstring, start/end lines). NO fixed-size window chunking — AST boundaries only. Handle module-level code as its own chunk.
- [ ] `embedder.py`: interface `Embedder.embed(texts: list[str]) -> list[vector]` with one concrete implementation; batch calls
- [ ] `vector_store.py`: Chroma collection per repo; upsert chunks with metadata; `search(query_text, k)` returns chunks
- [ ] `structural.py`: build a call graph (which functions call which) and import index using AST analysis; store as adjacency maps; support queries: `callers_of(qualified_name)`, `tests_for(qualified_name)` (heuristic: test files importing or naming the function)
- [ ] `pipeline.py`: `index_repo(path)` runs chunk → embed → store + builds structural index; idempotent re-runs; report stats (chunks, time, cost)
- [ ] Inspection CLI: `autoreview index <repo_path>` and `autoreview search <repo_path> "<query>"` to manually poke at retrieval quality

Exit criteria: index a real mid-size open-source Python repo; manual searches return sensibly relevant chunks; `callers_of` returns correct results spot-checked against grep.

Key learning targets: AST parsing, chunking strategy, embeddings, vector search mechanics, structural code analysis.

### Phase 3 — RAG: hybrid retrieval in the review loop (~4 days)

**Goal:** Reviews are informed by retrieved repo context, not just the diff.

Tasks:
- [ ] `retriever.py`: given changed functions from a diff, (a) vector-search top-k similar chunks, (b) structural lookup of callers + tests + the pre-change version of changed code, (c) merge, dedupe, and rank (structural hits rank above pure-similarity hits for direct relationships)
- [ ] `context_pack.py`: assemble `ContextPack` = diff hunks + retrieved chunks + a one-paragraph repo map summary, packed within a configurable token budget; truncation strategy: drop lowest-ranked retrieval first, never truncate the diff
- [ ] Wire `ContextPack` into the phase 1 agent prompt
- [ ] Add a `--no-rag` flag to the CLI so with/without comparison is trivial (this sets up phase 5 experiments)

Exit criteria: same PR reviewed with and without `--no-rag` produces visibly different (and subjectively better) findings on at least one test case where the bug requires cross-file context.

Key learning targets: hybrid retrieval, ranking/merging strategies, token budget management, context engineering.

### Phase 4 — Multi-agent orchestration (~4 days)

**Goal:** LangGraph graph with parallel specialists and a synthesizer.

Tasks:
- [ ] `graph.py`: LangGraph state graph — orchestrator node → parallel fan-out to bug/security/style agents → fan-in to synthesizer → output. Shared state carries the `ContextPack` and accumulates findings.
- [ ] Each sub-agent: focused system prompt (in `prompts/`), same `Finding` output schema, independent model config (so routing experiments are config changes, not code changes)
- [ ] `synthesizer.py`: dedupe overlapping findings (same file+line range+category), apply confidence gate (configurable threshold, default 0.6), rank by severity then confidence
- [ ] Reliability: per-agent timeout; if one agent fails, the review still completes with a noted gap; retries at the node level
- [ ] Cost accounting: tokens + dollars per node per review, included in review metadata
- [ ] Keep a `--single-agent` flag that runs the phase 1 mega-prompt path (for phase 5 ablation)

Exit criteria: full graph runs on real PRs; killing one sub-agent (simulated failure) still produces a partial review; cost report prints per review.

Key learning targets: LangGraph, parallel agent patterns, graceful degradation, model routing, cost engineering.

### Phase 5 — Evals and experiments (~5 days) ← THE DIFFERENTIATOR

**Goal:** Prove the system works, with numbers. This phase produces the resume bullet.

Tasks:
- [ ] `mine_dataset.py`: mine open-source Python repos for labeled examples. Strategy: find merged PRs/commits whose message indicates a bug fix (and ideally link to an issue); the parent state of the fix is the "buggy input," the fix diff localizes the ground-truth bug (file + approximate lines). Target ~50–100 buggy examples + ~30 clean PRs as negatives. Store as metadata (repo, SHA, PR number, label file/lines, category) — do not vendor the repos.
- [ ] `harness.py`: for each benchmark item, check out the state, run AutoReview, match findings against labels (a finding "hits" if it flags the labeled file within N lines of the labeled range with a plausible category)
- [ ] `metrics.py`: precision, recall, false-positive rate (findings on clean PRs), severity calibration, cost-per-review, latency
- [ ] Trace logging to Braintrust/Langfuse for every harness run; tag runs with config (rag on/off, agent mode, model routing)
- [ ] CI integration: GitHub Action runs a small smoke-eval subset on every push to prompts/ or agents/; full suite on demand
- [ ] Run and document 3 experiments:
  1. RAG ablation: `--no-rag` vs. full hybrid retrieval (also: vector-only vs. structural-only vs. hybrid if time permits)
  2. Architecture ablation: `--single-agent` mega-prompt vs. parallel specialists
  3. Model routing: all-Sonnet vs. mixed Sonnet/Haiku per role
- [ ] Write up results: a results table + 3–5 paragraph analysis per experiment in `evals/experiments/RESULTS.md`

Exit criteria: a results table with real numbers exists; at least one experiment produced a non-obvious finding worth writing about.

Key learning targets: eval methodology, benchmark construction, ablation design, experiment tracking, regression testing for LLM systems.

### Phase 6 — Production surface + artifacts (~4 days)

**Goal:** Packaging that gets interviews. Scope this down before scoping down phase 5.

Tasks:
- [ ] GitHub App: registration, webhook endpoint (signature verification), installation auth flow
- [ ] `server/app.py` + `worker.py`: webhook → enqueue review job (idempotent on PR head SHA) → worker runs pipeline → posts GitHub review with inline comments
- [ ] Streaming agent trace: SSE endpoint emitting graph events (node start/finish, findings as they arrive); minimal web UI consuming it
- [ ] README: leads with the eval results table and an architecture diagram, then quickstart, then design decisions with links to experiment writeups
- [ ] 2-minute demo video: install app → open PR → watch trace → see review on GitHub
- [ ] Blog-style writeup of the most non-obvious experiment finding

Fallback if time-constrained: skip the GitHub App entirely; polish the CLI, README, and demo video. A CLI with airtight evals beats a polished app with no measurement.

---

## Conventions and guardrails

- **Structured everything.** No agent emits free text into the pipeline. If you find yourself regex-parsing an LLM response, stop and use structured output instead.
- **Config over code for experiments.** Model choice, thresholds, RAG on/off, agent mode — all config flags, so every ablation is a config diff.
- **Log every LLM call** (prompt, response, tokens, cost, latency) from day one. Phase 5 depends on this discipline.
- **Prompts are versioned artifacts.** They live in `prompts/`, change via PR, and changes trigger the smoke eval.
- **Secrets via environment variables only.** Never commit keys. `.env.example` documents required vars.
- **Tests:** unit tests for diff parsing, chunking, retrieval ranking, synthesizer dedup logic (the deterministic parts). LLM-dependent behavior is covered by the eval harness, not unit tests.
- **Commit per task checkbox** where practical; keep commits small and message them clearly — this repo will be read by interviewers.
- **Python style:** type hints everywhere, ruff for lint/format, no clever metaprogramming. Readability is a feature of a portfolio repo.

## Definition of done (whole project)

1. `autoreview review <pr_url>` works end-to-end with hybrid RAG and parallel agents
2. Benchmark dataset of 80+ labeled examples exists and is reproducible via `mine_dataset.py`
3. Eval harness reports precision/recall/FPR and runs in CI
4. Three documented experiments with results tables in `evals/experiments/RESULTS.md`
5. README leads with results; demo video recorded
6. (Stretch) GitHub App installed and reviewing PRs on a live repo

## Working with this spec

- Implement phases strictly in order; within a phase, follow task order unless there's a clear reason not to
- Before writing code for a task, briefly state the design approach and any decisions being made
- At each phase boundary, run the exit criteria and summarize results before proceeding
- If a decision isn't covered by this spec, prefer the option that is (a) more measurable, (b) simpler, in that order
