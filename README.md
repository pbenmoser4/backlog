# backlog

An MCP server that wraps GitHub Issues as a lightweight backlog for Claude Code. Lets Claude create, track, and resolve work items using your GitHub repo as the backend — no extra database or token management required.

## How it works

The server exposes 8 tools to Claude via the [Model Context Protocol](https://modelcontextprotocol.io/):

| Tool | Description |
|------|-------------|
| `create_backlog_item` | Open a new issue with type and priority labels |
| `list_backlog_items` | List issues filtered by status, type, or priority |
| `get_backlog_item` | Fetch full issue details including comments |
| `search_backlog` | Full-text search across open issues |
| `start_working_on` | Mark an item in-progress |
| `add_progress_note` | Add a comment to track progress or log a decision |
| `complete_backlog_item` | Close an issue with a resolution summary |
| `reopen_backlog_item` | Reopen a closed issue with rationale |

All GitHub operations go through the `gh` CLI — no personal access tokens to manage.

## Prerequisites

- Python 3.8+
- [GitHub CLI](https://cli.github.com/) installed and authenticated (`gh auth login`)

## Setup

```bash
# Configure for a specific repo
python3 setup.py owner/repo

# Or run interactively and enter the repo when prompted
python3 setup.py
```

The setup script:
1. Verifies `gh` is installed and authenticated
2. Creates the required labels in your GitHub repo (status, type, priority)
3. Registers the MCP server in `~/.claude.json`
4. Prints a CLAUDE.md snippet to add to your project

## Configuration

The server is registered in `~/.claude.json` with an environment variable pointing at your repo:

```json
{
  "mcpServers": {
    "backlog": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/server.py"],
      "env": { "BACKLOG_REPO": "owner/repo" }
    }
  }
}
```

### Repo resolution

Every tool has an optional `repo_name` parameter. The server resolves which repo to use in this order:

1. **`repo_name` argument** — passed directly in the tool call
2. **Auto-detect from cwd** — runs `gh repo view` in the current working directory; works automatically when Claude is open inside a git repo with a GitHub remote
3. **`BACKLOG_REPO` env var** — the global default set in `~/.claude.json`, used as a fallback when no repo can be inferred from context

This means the server will naturally target whichever GitHub repo you have open in your editor, falling back to the configured default only when necessary.

## Labels

Setup creates three label groups in your repo:

| Group | Values |
|-------|--------|
| **Status** | `backlog`, `in-progress`, `blocked` |
| **Type** | `feature`, `bug`, `design`, `research`, `question` |
| **Priority** | `priority:high`, `priority:medium`, `priority:low` |
