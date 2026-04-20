#!/usr/bin/env python3
"""CLI for the AI-Powered Document Management Platform."""
import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="mindcampus", help="AI Document Management Platform CLI")
console = Console()

TOKEN_FILE = Path.home() / ".mindcampus_token"
DEFAULT_BASE_URL = os.environ.get("PLATFORM_URL", "http://localhost:8080")


def _load_token() -> Optional[str]:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


def _save_token(token: str):
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)


def _auth_headers() -> dict:
    token = _load_token()
    if not token:
        console.print("[red]Not logged in. Run: python cli.py login[/red]")
        raise typer.Exit(1)
    return {"Authorization": f"Bearer {token}"}


@app.command()
def login(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True),
    base_url: str = typer.Option(DEFAULT_BASE_URL),
):
    """Login and save token to ~/.mindcampus_token."""
    with httpx.Client() as client:
        try:
            resp = client.post(f"{base_url}/api/v1/auth/login", json={"email": email, "password": password})
            resp.raise_for_status()
            token = resp.json()["access_token"]
            _save_token(token)
            console.print("[green]Login successful![/green]")
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Login failed: {e.response.status_code}[/red]")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1)


@app.command()
def logout():
    """Remove saved token."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        console.print("[green]Logged out.[/green]")
    else:
        console.print("Not logged in.")


@app.command(name="create-doc")
def create_doc(
    title: str = typer.Option(..., prompt=True),
    content: str = typer.Option(..., prompt=True),
    tags: Optional[str] = typer.Option(None, help="Comma-separated tags"),
    base_url: str = typer.Option(DEFAULT_BASE_URL),
):
    """Create a new document."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    with httpx.Client() as client:
        try:
            resp = client.post(
                f"{base_url}/api/v1/documents",
                json={"title": title, "content": content, "tags": tag_list},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            doc = resp.json()
            console.print(f"[green]Created document:[/green] {doc['id']}")
            console.print(f"  Title: {doc['title']}")
            console.print(f"  Tags:  {doc.get('tags', [])}")
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error {e.response.status_code}: {e.response.text}[/red]")
            raise typer.Exit(1)


@app.command(name="list-docs")
def list_docs(
    limit: int = typer.Option(10, help="Number of docs to show"),
    skip: int = typer.Option(0, help="Offset"),
    base_url: str = typer.Option(DEFAULT_BASE_URL),
):
    """List documents in a table."""
    with httpx.Client() as client:
        try:
            resp = client.get(
                f"{base_url}/api/v1/documents",
                params={"limit": limit, "skip": skip},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            docs = resp.json()
            table = Table("ID", "Title", "Tags", "Created")
            for d in docs:
                table.add_row(
                    d["id"][:8] + "...",
                    d["title"][:40],
                    ", ".join(d.get("tags") or []),
                    d["created_at"][:10],
                )
            console.print(table)
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error {e.response.status_code}[/red]")
            raise typer.Exit(1)


@app.command(name="get-doc")
def get_doc(
    id: str = typer.Option(..., help="Document ID"),
    base_url: str = typer.Option(DEFAULT_BASE_URL),
):
    """Get a single document."""
    with httpx.Client() as client:
        try:
            resp = client.get(f"{base_url}/api/v1/documents/{id}", headers=_auth_headers())
            resp.raise_for_status()
            doc = resp.json()
            console.print(f"[bold]{doc['title']}[/bold] ({doc['id']})")
            console.print(f"Tags: {doc.get('tags', [])}")
            console.print(f"\n{doc['content']}")
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error {e.response.status_code}[/red]")
            raise typer.Exit(1)


@app.command()
def summarize(
    id: str = typer.Option(..., help="Document ID"),
    max_length: int = typer.Option(150, help="Max words in summary"),
    base_url: str = typer.Option(DEFAULT_BASE_URL),
):
    """Summarize a document using AI."""
    with httpx.Client() as client:
        try:
            resp = client.post(
                f"{base_url}/api/v1/documents/{id}/summarize",
                json={"max_length": max_length},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            console.print(f"[bold]Summary[/bold] (model: {data['model_used']})")
            console.print(f"Original: {data['original_length']} words → Summary: {data['summary_length']} words")
            console.print(f"\n{data['summary']}")
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error {e.response.status_code}: {e.response.text}[/red]")
            raise typer.Exit(1)


@app.command()
def search(
    query: str = typer.Option(..., help="Search query"),
    semantic: bool = typer.Option(False, help="Use semantic search"),
    limit: int = typer.Option(10),
    base_url: str = typer.Option(DEFAULT_BASE_URL),
):
    """Search documents."""
    with httpx.Client() as client:
        try:
            if semantic:
                resp = client.post(
                    f"{base_url}/api/v1/documents/search/semantic",
                    json={"query": query, "limit": limit},
                    headers=_auth_headers(),
                )
            else:
                resp = client.get(
                    f"{base_url}/api/v1/documents/search",
                    params={"q": query},
                    headers=_auth_headers(),
                )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                console.print("No results found.")
                return
            table = Table("ID", "Title", "Score" if semantic else "")
            for r in results:
                score = f"{r.get('similarity_score', 0):.3f}" if semantic else ""
                table.add_row(r["id"][:8] + "...", r["title"][:50], score)
            console.print(table)
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Error {e.response.status_code}[/red]")
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
