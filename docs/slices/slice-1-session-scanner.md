# Slice 1: Claude Code session scanner

## Goal

One record per Claude Code session with what is needed to group sessions into work threads and to judge their state: where it ran, what it changed, what git actions it took, how it ended, and which sessions are forks of each other. Grouping into threads is the next slice; this one only extracts facts.

## Scope

- Source: `~/.claude/projects/<project-dir>/<session-id>.jsonl` (top-level transcripts, 147 on 2026-11-04). Subagent transcripts (`<session-id>/subagents/*.jsonl`, 371) are not separate sessions: count them per parent session only.
- Codex is out of scope for this slice.
- **Read-only.** Never writes under `~/.claude`.
- **Incremental.** A cache (`out/.cache/sessions-cache.json`) keyed by transcript path stores size and mtime; unchanged files are not re-parsed. `--full` ignores the cache.
- Malformed lines are skipped and counted; one bad file never stops the run.

## Transcript format (observed 2026-11-04)

Each line is a JSON object with `type`. Relevant types and fields:

| type | Fields used |
|---|---|
| `user`, `assistant`, `system` | `sessionId`, `uuid`, `parentUuid`, `timestamp`, `cwd`, `gitBranch`, `isSidechain`, `message` |
| `custom-title` | `customTitle` |
| `agent-name` | `agentName` |
| `ai-title` | `aiTitle` |
| `relocated` | `relocatedCwd` |
| `last-prompt` | `lastPrompt` |

Tool calls are `assistant` messages whose `message.content[]` has items `{type: "tool_use", name, input}`.

The format is undocumented and may change: unknown types are ignored, missing fields yield `null`.

## Facts per session

- `sessionId`, `transcriptPath`, `projectDir`.
- `title`: last `custom-title`, else last `agent-name`, else last `ai-title`, else `null`; plus `titleSource`.
- `firstAt`, `lastAt` (timestamps), `userMessages`, `assistantMessages`, `subagentTranscripts`.
- `cwds`: distinct `cwd` values with counts; `relocatedCwd` if any.
- `gitBranches`: distinct `gitBranch` values with counts. Transcripts record `HEAD` when the session is not on a branch (detached); `HEAD`, empty string and missing are excluded and counted together in `detachedOrNoBranchCount`.
- `writes`: paths from `Write`, `Edit`, `MultiEdit`, `NotebookEdit` inputs (`file_path` / `notebook_path`), normalized to absolute forward-slash paths, with counts.
- `writeAnchor`: the root that holds most writes, and its share (0..1). Root resolution for a path, first match wins:
  1. the nearest ancestor containing `.git` (dir or file), resolved on disk at scan time;
  2. under `~/.claude/`: the first two components below it (for example `~/.claude/skills/latex-pdf`);
  3. the file's parent directory.
  `null` when the session wrote nothing.
- `gitActions`: counts of `commit`, `push`, `merge`, `pr-create` detected in `Bash` / `PowerShell` tool inputs (`git commit`, `git push`, `git merge`, `gh pr create`, `az repos pr create`), with the last timestamp of each.
- `closure`: signals of how the session ended:
  - `lastRecap`: the `recap` of the last `mcp__ccd_turn__wrap_up` call, truncated to 300 characters;
  - `lastAsk`: its `ask`, if any;
  - `sessionSummarySaved`: whether a `mem_session_summary` tool was called;
  - `endedWithQuestion`: the last assistant text ends with `?`.
- `fork`: see below.

Not stored: full message text, tool outputs, file contents. `lastPrompt` is stored truncated to 200 characters, since it is the best resume hint.

## Fork detection

Observed on real transcripts (2026-11-04): a forked session starts with a copy of its parent's history that keeps the **original message `uuid`s and timestamps**. Parent and fork therefore have the same `firstAt` and each contains the other's first `uuid`, so start times cannot tell them apart. Families of three or more sessions occur.

1. **Families (undirected).** Sessions sharing at least one message `uuid` are linked; families are the connected components (union-find over shared `uuid`s), so two members may be linked only through a third.
2. **Parent of a pair (best effort, directed).** The shared `uuid`s form a common prefix. Each side's divergence point is its first message, in file order, whose `uuid` is not shared. The parent is the side whose divergence point has the earliest timestamp. If the timestamps are equal, or one side has no non-shared message, the earlier transcript creation time wins (`st_birthtime` when available, else `st_ctime` on Windows). Still tied: unknown.
3. **Per session**, `fork` is `null` when the session shares no `uuid`, else:
   - `familyId`: the lexicographically smallest `sessionId` in the family;
   - `members`: the other `sessionId`s of the family;
   - `sharedMessages`: the largest number of `uuid`s shared with any member;
   - `parent`: the member it shares the most `uuid`s with (ties: smallest `sessionId`), only if that member is its parent by rule 2; else `null`;
   - `divergedAt`: timestamp of the session's own first non-shared message relative to that member, or `null` when it has none.

## Output

- `out/sessions.json`: `schemaVersion: 2` (2 replaced `forkOf` with `fork`), `generatedAt`, `sourceRoot`, `stats` (files scanned, parsed, cached, skipped lines), `sessions[]`.
- `out/sessions.md`: sessions grouped by `writeAnchor` (fallback main `cwd`), most recent first, with title, dates, branch, git actions, closure recap, and fork marks.
- CLI: `python -m work_ledger sessions [--source DIR] [--out DIR] [--full]`. Default source `~/.claude/projects`.

## Engineering constraints

- Same as slice 0: Python 3.14 stdlib, `unittest`, TDD.
- Tests use synthetic JSONL fixtures written to temp dirs, built from the observed format above. No test reads the real `~/.claude`.
- Streaming parse (line by line); never load a whole transcript into memory at once.
- Parsing (pure, per transcript), anchor resolution (filesystem) and fork detection (across sessions) are separate functions.

## First real run (2026-11-04)

147 sessions, 523 MB of top-level transcripts: 3.5 s full parse, 0.3 s cached. 167 tests passing.

- **Titles**: custom-title 98, ai-title 4, none 45.
- **Fork families**: 8 families with 19 sessions. Sessions titled "(fork)" were assigned as children in every case, which supports the parent rule.
- **Cross-thread fork found**: session S4 (an accent-mark fix with historical snapshots) shares 304 messages with the family of session S6 (a work-item monitor for system A). It was forked from the monitoring session and became a separate work thread, which is the cross-repo pattern described in [03-work-thread-model.md](../03-work-thread-model.md). Fork families are evidence of relation, not of being the same thread.
- **Write anchors**: 77 sessions wrote nothing (exploration, reviews, browser testing). The rest anchor mostly to repos and to worktrees under `<repo>/.claude/worktrees/`.

### Issues for the next slice

1. **Scratchpad anchors**: some sessions anchor to their temp scratchpad (`%TEMP%/claude/.../scratchpad`). Temp paths must be excluded from anchor computation.
2. **Worktree anchors are separate roots**: a worktree path must resolve to its main repo + branch to join its thread. The git inventory already has that mapping.
3. **Weak titles**: one session's title is a side question ("btw: ..."). Title is a display field, not a grouping key.
