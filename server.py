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
  create_spike          — open a formal research spike
  check_research        — surface prior research before starting work
  save_research_output  — persist spike findings to research/ directory
"""
import json
import logging
import os
import re
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
        "Use create_spike for formal research investigations that require plan mode and web research before implementation. "
        "Use check_research before starting any research task to surface prior findings. "
        "Use start_working_on when beginning a task. "
        "Use save_research_output to persist spike findings to the research/ directory. "
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


def _slugify(text: str) -> str:
    """Convert a title to a URL-safe slug (max 60 chars)."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:60].strip("-")


def _project_root() -> str:
    """Return the git repo root of the current working directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return os.getcwd()


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
    spikes_only: bool = False,
    limit: int = 25,
    repo_name: str = "",
) -> str:
    """
    List backlog items from GitHub Issues.

    Args:
        status: open | in-progress | blocked | closed | all
        type: feature | bug | design | research | question (optional filter)
        priority: high | medium | low (optional filter)
        spikes_only: if True, return only research spike items
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
    if spikes_only:
        args += ["--label", "spike"]
    elif status in ("in-progress", "blocked"):
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

    If the item is a research spike, returns explicit instructions to enter
    plan mode and use check_research before proceeding.

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
    issue = gh_json(
        "issue", "view", str(issue_number), "--repo", r,
        "--json", "labels",
    )
    label_names = {l["name"] for l in issue.get("labels", [])}
    if "spike" in label_names:
        return (
            f"#{issue_number} is now in-progress.\n\n"
            "SPIKE DETECTED: Enter plan mode. Call check_research to find prior work, "
            "then use WebSearch/WebFetch to answer the research questions. "
            "Call save_research_output with your findings before completing this item."
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

    For research spikes, call save_research_output first to persist findings,
    then call this to close the issue.

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


# ── Research Spike Tools ───────────────────────────────────────────────────────


@mcp.tool()
def create_spike(
    title: str,
    goal: str,
    research_questions: str,
    success_criteria: str,
    background: str = "",
    scope_limits: str = "",
    priority: str = "medium",
    repo_name: str = "",
) -> str:
    """
    Create a formal research spike backlog item.

    A spike is a time-boxed investigation that MUST be executed in plan mode
    with web research before any implementation begins.

    WHEN PICKING UP A SPIKE: enter plan mode immediately, call check_research
    to find prior work, use WebSearch/WebFetch to answer all research questions,
    then call save_research_output with your findings before completing the item.

    Args:
        title: Short title (e.g. "Evaluate vector DB options for embedding search")
        goal: One sentence stating what question the spike must answer
        research_questions: Specific sub-questions to answer (use newline-separated bullets)
        success_criteria: What the output doc must contain for the spike to be done
        background: Why is this spike needed? What triggered it?
        scope_limits: What is explicitly out of scope
        priority: high | medium | low
        repo_name: owner/name (falls back to BACKLOG_REPO env var)

    Returns the issue number, URL, and expected output file path.
    """
    r = repo(repo_name)
    if priority not in VALID_PRIORITIES:
        priority = "medium"

    slug = _slugify(title)

    body_parts = [f"## Goal\n{goal}"]
    if background:
        body_parts.append(f"## Background\n{background}")
    body_parts.append(f"## Research Questions\n{research_questions}")
    body_parts.append(f"## Success Criteria\n{success_criteria}")
    if scope_limits:
        body_parts.append(f"## Scope Limits\n{scope_limits}")
    # Output path placeholder — filled in after issue is created
    body_parts.append("## Output\n_To be filled in by the completing agent._")

    body = "\n\n".join(body_parts)

    labels = ["backlog", "research", "spike", f"priority:{priority}"]
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
    output_path = f"research/{number}-{slug}.md"

    # Update the issue body with the concrete output path
    final_body = body.replace(
        "## Output\n_To be filled in by the completing agent._",
        f"## Output\n`{output_path}`",
    )
    gh("issue", "edit", number, "--repo", r, "--body", final_body)

    return f"Created spike #{number}: {title}\n{url}\nExpected output: {output_path}"


@mcp.tool()
def check_research(
    topic: str,
    repo_name: str = "",
) -> str:
    """
    Check whether research has already been done on a topic.

    ALWAYS call this before beginning a research spike or before implementing
    something that may have required prior research. Searches two sources:
      1. The research/ directory in the current working repo (local markdown files)
      2. GitHub Issues labeled 'spike' matching the topic (open and closed)

    Args:
        topic: Keywords describing what you're researching
        repo_name: owner/name for backlog repo (falls back to BACKLOG_REPO env var)

    Returns existing research file summaries and spike issue matches, or a
    message indicating no prior research was found.
    """
    results: list[str] = []

    # 1. Scan local research/ directory
    research_dir = os.path.join(_project_root(), "research")
    if os.path.isdir(research_dir):
        keywords = [kw.lower() for kw in topic.split()]
        matches = []
        for fname in sorted(os.listdir(research_dir)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(research_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                head = content[:500].lower()
                if any(kw in fname.lower() or kw in head for kw in keywords):
                    excerpt = content[:200].strip()
                    matches.append(f"  {fname}\n    {excerpt!r}")
            except OSError:
                continue
        if matches:
            results.append("Local research files matching '{}':\n{}".format(
                topic, "\n\n".join(matches)
            ))

    # 2. Search GitHub spike issues
    try:
        r = repo(repo_name)
        search_query = f"{topic} repo:{r} label:spike"
        issues = gh_json(
            "search", "issues",
            search_query,
            "--limit", "10",
            "--json", "number,title,state,url",
        )
        if issues:
            lines = [f"GitHub spike issues matching '{topic}':"]
            for issue in issues:
                lines.append(f"  #{issue['number']} [{issue['state']}] {issue['title']}\n  {issue['url']}")
            results.append("\n\n".join(lines))
    except Exception:
        pass

    if not results:
        return f"No prior research found for '{topic}'."
    return "\n\n---\n\n".join(results)


@mcp.tool()
def save_research_output(
    issue_number: int,
    content: str,
    repo_name: str = "",
) -> str:
    """
    Save the output of a completed research spike to the research/ directory.

    Call this AFTER completing your web research and synthesizing findings,
    and BEFORE calling complete_backlog_item. Writes the content to
    research/<issue_number>-<slug>.md in the project root, ensures the
    directory is gitignored, and posts a comment on the issue linking to
    the file.

    Args:
        issue_number: The spike issue number
        content: Full markdown content of the research output
        repo_name: owner/name for backlog repo (falls back to BACKLOG_REPO env var)

    Returns the path where the file was written.
    """
    r = repo(repo_name)

    # Fetch issue title to build the filename
    issue = gh_json(
        "issue", "view", str(issue_number), "--repo", r,
        "--json", "title",
    )
    slug = _slugify(issue["title"])
    filename = f"{issue_number}-{slug}.md"

    # Write to research/ in the project root
    project_root = _project_root()
    research_dir = os.path.join(project_root, "research")
    os.makedirs(research_dir, exist_ok=True)

    # Ensure research/ is gitignored
    gitignore_path = os.path.join(project_root, ".gitignore")
    gitignore_entry = "research/"
    try:
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                existing = f.read()
            if gitignore_entry not in existing.splitlines():
                with open(gitignore_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{gitignore_entry}\n")
        else:
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(f"{gitignore_entry}\n")
    except OSError:
        pass  # Non-fatal: best effort gitignore update

    output_path = os.path.join(research_dir, filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Post a comment on the issue
    rel_path = f"research/{filename}"
    gh(
        "issue", "comment", str(issue_number), "--repo", r,
        "--body", f"Research output saved to `{rel_path}`.",
    )

    return f"Research output written to {output_path}"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
