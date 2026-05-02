# backlog

An MCP server that wraps GitHub Issues as a lightweight backlog for Claude Code. Lets Claude create, track, and resolve work items using your GitHub repo as the backend — no extra database or token management required.

## How it works

The server exposes 11 tools to Claude via the [Model Context Protocol](https://modelcontextprotocol.io/):

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
| `create_spike` | Open a formal research spike |
| `check_research` | Surface prior research before starting an investigation |
| `save_research_output` | Persist spike findings to `research/` in the working repo |

All GitHub operations go through the `gh` CLI — no personal access tokens to manage.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [GitHub CLI](https://cli.github.com/) installed and authenticated (`gh auth login`)

## Installation

```bash
uvx gh-backlog-mcp --setup owner/repo
```

That's it. `uvx` fetches the package from PyPI on demand — no cloning, no `pip install`. The setup command:

1. Verifies `gh` is installed and authenticated
2. Creates the required labels in your GitHub repo
3. Registers the MCP server in `~/.claude.json`
4. Prints a CLAUDE.md snippet to add to your project

Restart Claude Code after setup to pick up the server.

## Configuration

Setup registers the server in `~/.claude.json` using `uvx`:

```json
{
  "mcpServers": {
    "backlog": {
      "type": "stdio",
      "command": "uvx",
      "args": ["gh-backlog-mcp"],
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
| **Modifier** | `spike` — stacks with `research` to mark formal investigations |
| **Priority** | `priority:high`, `priority:medium`, `priority:low` |

## Research Spikes

A research spike is a formal investigation item that signals to the agent picking it up: enter plan mode, do web research, and produce a written output before any implementation begins.

### Creating a spike

```
create_spike(
  title="Evaluate vector DB options for embedding search",
  goal="Determine which vector database best fits our latency and cost requirements",
  research_questions="- What are the top open-source options?\n- How do they compare on query latency at 1M vectors?\n- What are the operational costs?",
  success_criteria="Output doc must include a comparison table and a recommendation with rationale",
  priority="high"
)
```

The issue is created with both `research` and `spike` labels. The body includes a structured template (Goal, Background, Research Questions, Success Criteria, Output path).

### Agent workflow for spikes

When an agent calls `start_working_on` on a spike, it receives explicit instructions to:

1. Enter plan mode
2. Call `check_research` to find any prior work on the topic
3. Use `WebSearch`/`WebFetch` to answer the research questions
4. Call `save_research_output` with the synthesized findings
5. Call `complete_backlog_item` to close the issue

### Research output files

`save_research_output` writes findings to `research/<issue-number>-<slug>.md` in the current working repository (determined via `git rev-parse --show-toplevel`). It also:

- Creates the `research/` directory if it doesn't exist
- Adds `research/` to `.gitignore` automatically so outputs are never accidentally committed
- Posts a comment on the GitHub issue linking to the file

### Checking prior research

```
check_research(topic="vector database")
```

Searches two sources:
1. Local `research/*.md` files — keyword match against filename and first 500 chars
2. GitHub spike issues (open and closed) matching the topic

Use this before creating a new spike or before implementing something that may have been researched previously.
