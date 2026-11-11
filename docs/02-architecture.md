# Architecture

## Three layers

| Layer | Responsibility | Covers |
|---|---|---|
| 1. Ledger (source of truth) | Scan sessions and repos, compute the state of each work thread | Commit/push/merge state, most advanced fork, pending work |
| 2. Views | Present the ledger | Compact panel, resume brief, periodic reminder |
| 3. Background jobs | Work on the ledger on a schedule | Reminder every 15 days, weekly curation of communication drafts |

Layers 2 and 3 are cheap only if layer 1 is reliable. Without a trustworthy ledger the panel lies and the drafts invent progress.

## Shape

```
 ~/.claude/projects/*.jsonl ─┐
 ~/.codex/sessions/*.jsonl ──┼─▶ [ core: scanner CLI ] ──▶ ledger.json
 git (state of each repo) ───┤      (no UI, idempotent)      overrides.json (manual marks)
 Engram ─────────────────────┘                │
                                              │ triggered by
                     ┌────────────────────────┼─────────────────────┐
                     ▼                        ▼                     ▼
           [ mod: Claude app pane ]   [ scheduled task ]    [ future tray app ]
            reads ledger via $.fs      15-day / weekly       reads the same ledger
            refreshes via $.process    (scanner + curator)
```

Hexagonal: the ledger and its state rules are the domain; the pane, the scheduled jobs and any future tray app are adapters over one contract (`ledger.json` + `overrides.json`). No view computes state.

## Data sources (verified 2026-11-03 on the work laptop)

| Source | Location | Readable | Notes |
|---|---|---|---|
| Claude Code (desktop app + CLI) | `~/.claude/projects/**/*.jsonl` | Yes | 508 transcripts. Primary source |
| Codex local | `~/.codex/sessions/`, `~/.codex/archived_sessions/` | Yes | 30 + 4 JSONL |
| Git | Each repo referenced by a session | Yes | Objective judge for commit/push/merge state |
| Engram | Local memory store | Yes | Session summaries and decisions |
| Claude desktop chat tab | Cloud (only browser cache locally) | No | Cache is not a reliable source |
| ChatGPT web / Codex web | Cloud | Manual export only | Out of MVP scope |

## Platform constraints for the pane (Claude Code mods, build 2.1.309)

Verified against the `plugin-authoring` API reference:

| Need | Supported | How |
|---|---|---|
| Read a local JSON file | Yes | `$.fs.read`, `list`, `stat` |
| Run a local process | Yes | `$.process.run` (argv) |
| Toast / native notification | Yes | `$.ui.toast`, `$.ui.notify` (native OS notification) |
| Timers | Only while the session lives | `$.clock.every` / `after`, reset on mod reload |
| Model calls | Yes | `$.model.complete` |
| State across sessions | Yes | `$.store` |
| Read other sessions | **No** | `$.session.messages()` sees only the current session |

Consequences:

- The pane cannot be the brain: it does not see other sessions. All logic lives in the scanner CLI.
- Scheduled work (15-day reminder, weekly curation) runs outside the mod: Windows Task Scheduler or the scheduled-tasks MCP, so it runs with no session open.
- A future Windows tray app is another adapter over the same files; no change to the core.

## Deployment scope

Single instance on the work laptop. The personal machine is out of scope.
