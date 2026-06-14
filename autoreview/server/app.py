"""
FastAPI server for AutoReview.

GET  /          — serves the review UI
POST /review    — runs the multi-agent graph and streams findings as SSE

SSE event format:
  event: finding
  data: <JSON Finding>

  event: done
  data: {"total": N}

  event: error
  data: {"message": "..."}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from autoreview.core.github_client import get_pr
from autoreview.retrieval.context_pack import ContextPack

logger = logging.getLogger(__name__)
app = FastAPI(title="AutoReview")

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ReviewRequest(BaseModel):
    pr_url: str


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text()


@app.post("/review")
def review(req: ReviewRequest):
    """Run the agent graph and stream findings as SSE."""

    def generate():
        try:
            diff_chunks = get_pr(req.pr_url)
            context = ContextPack(diff_chunks=diff_chunks)

            # Run each agent individually so we can stream findings as they arrive
            from pathlib import Path as P
            from autoreview.agents.base import run_agent
            from autoreview.agents.synthesizer import synthesize

            PROMPTS = P(__file__).parent.parent / "agents" / "prompts"

            raw = []
            for name, prompt_file in [
                ("bug", PROMPTS / "bug.txt"),
                ("security", PROMPTS / "security.txt"),
                ("style", PROMPTS / "style.txt"),
            ]:
                findings = run_agent(name, prompt_file, context)
                raw.extend(findings)
                for f in findings:
                    payload = f.model_dump()
                    payload["agent"] = name
                    yield f"event: finding\ndata: {json.dumps(payload)}\n\n"

            final = synthesize(raw)
            yield f"event: done\ndata: {json.dumps({'total': len(final)})}\n\n"

        except Exception as e:
            logger.exception("Review failed for %s", req.pr_url)
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
