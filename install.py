#!/usr/bin/env python3
"""
setup.py — Installer for the backlog MCP server.

Usage:
  python3 setup.py owner/repo          # configure for a specific repo
  python3 setup.py                      # prompts for repo

What it does:
  1. Verifies gh CLI is installed and authenticated
  2. Creates backlog labels in the target GitHub repo
  3. Adds the backlog MCP server to ~/.claude/settings.json
  4. Prints a CLAUDE.md snippet to add to your project
"""
import json
import os
import pathlib
import subprocess
import sys

CLAUDE_JSON = pathlib.Path.home() / ".claude.json"          # MCP server registry
SETTINGS_PATH = pathlib.Path.home() / ".claude" / "settings.json"  # hooks/permissions
SERVER_PATH = pathlib.Path(__file__).parent / "server.py"
PYTHON_BIN = sys.executable  # use whatever python ran this script

# ── Label definitions ─────────────────────────────────────────────────────────

LABELS = [
    # Status
    ("backlog",       "0075ca", "New item, not yet started"),
    ("in-progress",   "e4e669", "Currently being worked on"),
    ("blocked",       "d93f0b", "Waiting on something"),
    # Type
    ("feature",       "a2eeef", "New functionality"),
    ("bug",           "d73a4a", "Something broken or incorrect"),
    ("design",        "7057ff", "Design decision needed before coding"),
    ("research",      "006b75", "Exploratory spike"),
    ("question",      "cc317c", "Open question needing an answer"),
    ("spike",         "f9d0c4", "Formal research spike — plan mode + web research required"),
    # Priority
    ("priority:high", "b60205", "High priority"),
    ("priority:medium","e99695","Medium priority"),
    ("priority:low",  "c5def5", "Low priority"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def ok(msg):   print(f"  \033[32m✓\033[0m {msg}")
def warn(msg): print(f"  \033[33m!\033[0m {msg}")
def info(msg): print(f"  \033[34m→\033[0m {msg}")
def fail(msg): print(f"  \033[31m✗\033[0m {msg}"); sys.exit(1)


def run(args: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def check_gh() -> str:
    """Verify gh is installed and authenticated. Returns the GitHub username."""
    code, out, err = run(["gh", "--version"])
    if code != 0:
        fail("gh CLI not found. Install from https://cli.github.com/")

    code, out, err = run(["gh", "auth", "status"])
    if code != 0:
        fail("gh CLI not authenticated. Run: gh auth login")

    # Extract username from auth status
    for line in (out + err).splitlines():
        if "Logged in to" in line and "account" in line:
            parts = line.split("account")
            if len(parts) > 1:
                username = parts[1].strip().split()[0]
                ok(f"gh authenticated as {username}")
                return username

    ok("gh authenticated")
    return ""


def create_labels(repo: str):
    """Create backlog labels in the target repo. Skips existing ones."""
    created = 0
    skipped = 0
    for name, color, description in LABELS:
        code, out, err = run([
            "gh", "label", "create", name,
            "--repo", repo,
            "--color", color,
            "--description", description,
            "--force",   # update if already exists
        ])
        if code == 0:
            created += 1
        else:
            warn(f"Could not create label '{name}': {err[:80]}")
            skipped += 1

    ok(f"Labels: {created} created/updated, {skipped} skipped")


def patch_settings(repo: str):
    """Add the backlog MCP server to ~/.claude.json (the MCP server registry)."""
    if not CLAUDE_JSON.exists():
        warn(f"~/.claude.json not found — skipping MCP registration")
        return

    with open(CLAUDE_JSON) as f:
        config = json.load(f)

    mcp_servers = config.setdefault("mcpServers", {})

    if "backlog" in mcp_servers:
        existing_repo = mcp_servers["backlog"].get("env", {}).get("BACKLOG_REPO", "")
        if existing_repo == repo:
            ok("backlog MCP server already configured in ~/.claude.json")
            return
        info(f"Updating backlog MCP server (was: {existing_repo}, now: {repo})")

    mcp_servers["backlog"] = {
        "type": "stdio",
        "command": PYTHON_BIN,
        "args": [str(SERVER_PATH)],
        "env": {"BACKLOG_REPO": repo},
    }

    with open(CLAUDE_JSON, "w") as f:
        json.dump(config, f, indent=2)

    ok(f"backlog MCP server added to ~/.claude.json → {repo}")


def print_claude_md_snippet(repo: str):
    """Print the CLAUDE.md snippet to add for agent instructions."""
    snippet = f"""
## Backlog Management

Use the backlog MCP tools to track work items throughout this session.

**When to create a backlog item** (call `create_backlog_item`):
- You identify a feature, improvement, or refactor that won't be done right now
- You find a bug you're not fixing in this session
- A design decision is needed before proceeding
- An open question is left unresolved

**Workflow:**
- `create_backlog_item` — new item (type: feature/bug/design/research/question, priority: high/medium/low)
- `start_working_on` — when beginning work on an item
- `add_progress_note` — record decisions, blockers, or partial progress
- `complete_backlog_item` — when done, with a resolution summary

Default repo: `{repo}`
"""
    print("\n" + "─" * 60)
    print("Add this to your project's CLAUDE.md:\n")
    print(snippet)
    print("─" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Determine target repo
    if len(sys.argv) > 1:
        target_repo = sys.argv[1]
    else:
        print("\nNo repo specified. Enter the GitHub repo to use for backlog tracking.")
        target_repo = input("Repo (owner/name): ").strip()
        if not target_repo or "/" not in target_repo:
            fail("Invalid repo format. Use owner/name (e.g. pbenmoser4/crucible)")

    print(f"\n\033[1mbacklog-setup\033[0m → {target_repo}\n")

    print("Checking prerequisites:")
    check_gh()

    print("\nCreating GitHub labels:")
    create_labels(target_repo)

    print("\nConfiguring MCP server:")
    patch_settings(target_repo)

    print_claude_md_snippet(target_repo)

    print(f"\n\033[1mDone.\033[0m")
    print(f"Restart Claude Code to pick up the new MCP server.")
    print(f"Then use create_backlog_item, list_backlog_items, etc. in any session.")


if __name__ == "__main__":
    main()
