from __future__ import annotations

import logging

import click
from dotenv import load_dotenv

load_dotenv()
from rich.console import Console
from rich.table import Table

from autoreview.core.github_client import get_pr
from autoreview.agents.reviewer import review
from autoreview.indexing.pipeline import index_repo, load_vector_store, load_structural
from autoreview.indexing.embedder import VoyageEmbedder
from autoreview.retrieval.retriever import retrieve
from autoreview.retrieval.context_pack import ContextPack, build_context_pack

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@click.group()
def main():
    pass


@main.command()
@click.argument("pr_url")
@click.option("--repo-path", default=None, help="Path to local repo index for RAG context.")
@click.option("--no-rag", is_flag=True, help="Skip RAG retrieval and review the diff only.")
def review_pr(pr_url: str, repo_path: str, no_rag: bool):
    """Review a GitHub PR."""
    from pathlib import Path
    console = Console()

    console.print(f"Fetching diff for {pr_url}...")
    diff_chunks = get_pr(pr_url)
    console.print(f"Got {len(diff_chunks)} diff chunks.")

    if repo_path and not no_rag:
        console.print("Retrieving context from index...")
        store = load_vector_store(Path(repo_path))
        structural = load_structural(Path(repo_path))
        ranked = retrieve(diff_chunks, store, structural)
        context = build_context_pack(diff_chunks, ranked)
        console.print(f"Added {len(context.context_chunks)} context chunks.")
    else:
        context = ContextPack(diff_chunks=diff_chunks)

    console.print("Running review...")
    result = review(pr_url, context)

    if not result.findings:
        console.print("[green]No issues found.[/green]")
    else:
        table = Table(title=f"Findings ({len(result.findings)})")
        table.add_column("Sev")
        table.add_column("Cat")
        table.add_column("File")
        table.add_column("Lines")
        table.add_column("Description", max_width=60)
        table.add_column("Conf")

        for f in result.findings:
            table.add_row(
                f.severity.value,
                f.category.value,
                f.file_path,
                f"{f.start_line}-{f.end_line}",
                f.description,
                f"{f.confidence:.1f}",
            )
        console.print(table)

    console.print(f"\nTokens: {result.token_usage}  Cost: ${result.cost_usd:.4f}  Latency: {result.latency_seconds}s")


@main.command()
@click.argument("repo_path")
def index(repo_path: str):
    """Index a local repo for RAG retrieval."""
    from pathlib import Path
    console = Console()
    console.print(f"Indexing {repo_path}...")
    stats = index_repo(Path(repo_path))
    console.print(f"Done. Files: {stats['files']}  Chunks: {stats['chunks']}  Time: {stats['latency_seconds']}s")


@main.command()
@click.argument("repo_path")
@click.argument("query")
@click.option("-k", default=5, help="Number of results to return")
def search(repo_path: str, query: str, k: int):
    """Search the index of a repo with a natural language query."""
    from pathlib import Path
    console = Console()
    store = load_vector_store(Path(repo_path))
    embedder = VoyageEmbedder()
    [query_vec] = embedder.embed([query])
    results = store.search(query_vec, k=k)
    for chunk in results:
        console.print(f"\n[bold]{chunk.qualified_name}[/bold] ({chunk.file_path} lines {chunk.start_line}-{chunk.end_line})")
        console.print(chunk.content[:300] + ("..." if len(chunk.content) > 300 else ""))
