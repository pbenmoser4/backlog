#!/usr/bin/env python3
"""
Backlog MCP Server — GitHub Issues wrapper for agent-native backlog management.

Uses the gh CLI for all GitHub operations (no token management required).
Configure default repo via BACKLOG_REPO env var (owner/name format).

Tools:
  create_backlog_item   — open a new backlog item
  list_backlog_items    — query the backlog
  get_backlog_item      — fetch a single item with full context
  add_progress_note     — append a comment (execution log)
  start_working_on      — move item to in-progress
  complete_backlog_item — close with resolution summary
  reopen_backlog_item   — reopen a closed item
  search_backlog        — full-text search across items
"""
import json
import logging
import os
import subprocess
import sys

# Redirect all logging to stderr so stdout stays clean for JSON-RPC
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

from mcp.server.fastmcp import FastMCP

# ── Configuration ─────────────────────────────────────────────────────────────

DEFAULT_REPO = os.environ.get("BACKLOG_REPO", "")

mcp = FastMCP(
    "backlog",
    instructions=(
        "Backlog management via GitHub Issues. "
        f"Default repo: {DEFAULT_REPO or '(set BACKLOG_REPO env var)'}. "
        "Use create_backlog_item when you identify future work. "
        "Use start_working_on when beginning a task. "
        "Use complete_backlog_item when done, with a resolution summary."
    ),
)

# ── Label taxonomy ────────────────────────────────────────────────────────────

VALID_TYPES = {"feature", "bug", "design", "research", "question"}
VALID_PRIORITIES = {"high", "medium", "low"}

# ── GitHub CLI helpers ────────────────────────────────────────────────────────


def gh(*args: str) -> str:
    """Run a gh CLI command, return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["gh"] + list(args),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh exited {result.returncode}")
    return result.stdout.strip()


def gh_json(*args: str) -> list | dict:
    """Run a gh CLI command that returns JSON, parse and return it."""
    raw = gh(*args)
    return json.loads(raw) if raw else []


def repo(r: str) -> str:
    """Resolve repo: explicit arg → gh auto-detect from cwd → BACKLOG_REPO env var."""
    if r:
        return r
    # Try to detect from current working directory
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # Fall back to global default
    if DEFAULT_REPO:
        return DEFAULT_REPO
    raise ValueError(
        "No repo specified. Pass repo='owner/name', set BACKLOG_REPO env var, "
        "or run from within a git repo."
    )


def format_issue(issue: dict) -> str:
    """Format a single issue dict as readable text."""
    labels = [l["name"] for l in issue.get("labels", [])]
    state = issue.get("state", "")
    return (
        f"#{issue['number']} [{state}] {issue['title']}\n"
        f"  Labels: {', '.join(labels) or 'none'}\n"
        f"  URL: {issue.get('url', '')}\n"
        f"  Created: {issue.get('createdAt', '')[:10]}"
    )


# ── MCP Tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def create_backlog_item(
    title: str,
    body: str,
    type: str = "feature",
    priority: str = "medium",
    repo_name: str = "",
) -> str:
    """
    Create a new backlog item as a GitHub Issue.

    Args:
        title: Short imperative title (e.g. "Add VAULT scoring curve")
        body: Full description — what needs to be done and why
        type: feature | bug | design | research | question
        priority: high | medium | low
        repo_name: owner/name (falls back to BACKLOG_REPO env var)

    Returns the issue URL and number.
    """
    r = repo(repo_name)
    if type not in VALID_TYPES:
        type = "feature"
    if priority not in VALID_PRIORITIES:
        priority = "medium"

    labels = ["backlog", type, f"priority:{priority}"]
    label_args: list[str] = []
    for label in labels:
        label_args += ["--label", label]

    url = gh(
        "issue", "create",
        "--repo", r,
        "--title", title,
        "--body", body,
        *label_args,
    )
    number = url.split("/")[-1]
    return f"Created #{number}: {title}\n{url}"


@mcp.tool()
def list_backlog_items(
    status: str = "open",
    type: str = "",
    priority: str = "",
    limit: int = 25,
    repo_name: str = "",
) -> str:
    """
    List backlog items from GitHub Issues.

    Args:
        status: open | in-progress | blocked | closed | all
        type: feature | bug | design | research | question (optional filter)
        priority: high | medium | low (optional filter)
        limit: max results (default 25)
        repo_name: owner/name (falls back to BACKLOG_REPO env var)

    Returns a formatted list of matching issues.
    """
    r = repo(repo_name)

    args = [
        "issue", "list", "--repo", r,
        "--limit", str(limit),
        "--json", "number,title,labels,state,createdAt,url",
    ]

    # State filter
    if status == "closed":
        args += ["--state", "closed"]
    elif status == "all":
        args += ["--state", "all"]
    else:
        args += ["--state", "open"]

    # Label filter — pick the most specific one
    if status in ("in-progress", "blocked"):
        args += ["--label", status]
    elif type:
        args += ["--label", type]
    elif status == "open":
        args += ["--label", "backlog"]

    if priority:
        args += ["--label", f"priority:{priority}"]

    issues = gh_json(*args)
    if not issues:
        return "No items found."

    lines = [f"Found {len(issues)} item(s):\n"]
    for issue in issues:
        lines.append(format_issue(issue))
    return "\n\n".join(lines)


@mcp.tool()
def get_backlog_item(issue_number: int, repo_name: str = "") -> str:
    """
    Fetch a single backlog item with its full description and comment history.

    Args:
        issue_number: GitHub issue number
        repo_name: owner/name (falls back to BACKLOG_REPO env var)

    Returns full issue detail including all comments.
    """
    r = repo(repo_name)
    issue = gh_json(
        "issue", "view", str(issue_number), "--repo", r,
        "--json", "number,title,body,labels,state,url,createdAt,comments",
    )
    labels = [l["name"] for l in issue.get("labels", [])]
    comments = issue.get("comments", [])

    parts = [
        f"#{issue['number']} [{issue['state']}] {issue['title']}",
        f"URL: {issue['url']}",
        f"Labels: {', '.join(labels) or 'none'}",
        f"Created: {issue.get('createdAt', '')[:10]}",
        "",
        "## Description",
        issue.get("body", "(no description)"),
    ]

    if comments:
        parts += ["", f"## Comments ({len(comments)})"]
        for c in comments:
            author = c.get("author", {}).get("login", "unknown")
            created = c.get("createdAt", "")[:10]
            parts.append(f"\n**{author}** ({created}):\n{c.get('body', '')}")

    return "\n".join(parts)


@mcp.tool()
def add_progress_note(
    issue_number: int,
    note: str,
    repo_name: str = "",
) -> str:
    """
    Add a progress note or execution log entry to a backlog item.

    Use this to record what you did, decisions made, or blockers encountered
    while working on an item. Creates a GitHub Issue comment.

    Args:
        issue_number: GitHub issue number
        note: The progress note or update
        repo_name: owner/name (falls back to BACKLOG_REPO env var)
    """
    r = repo(repo_name)
    gh("issue", "comment", str(issue_number), "--repo", r, "--body", note)
    return f"Progress note added to #{issue_number}."


@mcp.tool()
def start_working_on(issue_number: int, repo_name: str = "") -> str:
    """
    Mark a backlog item as in-progress.

    Removes the 'backlog' label, adds 'in-progress'. Call this when you
    begin actively working on an item.

    Args:
        issue_number: GitHub issue number
        repo_name: owner/name (falls back to BACKLOG_REPO env var)
    """
    r = repo(repo_name)
    gh(
        "issue", "edit", str(issue_number), "--repo", r,
        "--add-label", "in-progress",
        "--remove-label", "backlog",
    )
    return f"#{issue_number} is now in-progress."


@mcp.tool()
def complete_backlog_item(
    issue_number: int,
    resolution: str,
    repo_name: str = "",
) -> str:
    """
    Mark a backlog item as complete and close it.

    Adds a resolution comment summarizing what was done, then closes the issue.
    Call this when work on an item is fully done.

    Args:
        issue_number: GitHub issue number
        resolution: Summary of what was done and how it was resolved
        repo_name: owner/name (falls back to BACKLOG_REPO env var)
    """
    r = repo(repo_name)
    gh("issue", "comment", str(issue_number), "--repo", r, "--body", resolution)
    gh("issue", "close", str(issue_number), "--repo", r)
    return f"#{issue_number} closed with resolution."


@mcp.tool()
def reopen_backlog_item(
    issue_number: int,
    reason: str = "",
    repo_name: str = "",
) -> str:
    """
    Reopen a closed backlog item.

    Args:
        issue_number: GitHub issue number
        reason: Optional reason for reopening
        repo_name: owner/name (falls back to BACKLOG_REPO env var)
    """
    r = repo(repo_name)
    if reason:
        gh("issue", "comment", str(issue_number), "--repo", r, "--body", reason)
    gh("issue", "reopen", str(issue_number), "--repo", r)
    gh(
        "issue", "edit", str(issue_number), "--repo", r,
        "--add-label", "backlog",
        "--remove-label", "in-progress",
    )
    return f"#{issue_number} reopened."


@mcp.tool()
def search_backlog(query: str, repo_name: str = "", limit: int = 20) -> str:
    """
    Search backlog items by keyword across titles and bodies.

    Args:
        query: Search terms
        repo_name: owner/name (falls back to BACKLOG_REPO env var)
        limit: Max results (default 20)
    """
    r = repo(repo_name)
    # GitHub search syntax: terms + repo scoping
    search_query = f"{query} repo:{r}"
    issues = gh_json(
        "search", "issues",
        search_query,
        "--limit", str(limit),
        "--json", "number,title,labels,state,url,createdAt",
    )
    if not issues:
        return f"No items found matching '{query}'."

    lines = [f"Found {len(issues)} item(s) matching '{query}':\n"]
    for issue in issues:
        lines.append(format_issue(issue))
    return "\n\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
