# Slice 6: resume copilot (`context` command and `retomar` skill)

## Goal

Projects get abandoned for weeks when priorities change. When the user comes back they need to know, quickly: what was project X about, where did it stand, what is pending, and what to do first. They did not save anything before leaving, and they will not start doing so.

Slice 6 rebuilds that context on demand and hands it to the in-session model, which writes a short brief and one next micro-step.

## Decisions (taken with the user, 2026-11-11)

- The ledger (`out/ledger.json`) stays the passive cross-project radar. Nothing depends on the user running a save or pause command.
- Context is reconstructed on demand from the ledger, live git state and the session transcripts, and synthesized at **project** level, not per thread.
- The user sets the priority ("exportadora is top priority"); the copilot supplies context plus **one** concrete next micro-step. No option menus.
- The entry point is manual, at the start of work: a skill the user invokes in a Claude Code session, so follow-up questions stay conversational.

## Why a ledger dump is not enough

On the real ledger, one project ("QA_Sispro_Exportadora") has 40+ threads. Many are `worktree-agent-<hex>` branch threads with no sessions; many `resume.lastPrompt` values are "si", "dale", "ya está"; `resume.lastRecap` is null for older sessions. The command therefore reduces noise and adds transcript excerpts.

## Design

`python -m work_ledger context [QUERY] [--ledger PATH] [--json] [--threads N] [--transcripts K] [--max-chars C] [--refresh]`

| Module | Role |
|---|---|
| `context_build.py` | Pure: matching, noise reduction, ranking, overview, size cap, Markdown and JSON rendering. I/O only through ports passed in |
| `context_git.py` | Live git state of one folder, through the shared `gitcmd.run_git` runner, with an allowlist of read-only commands |
| `context_transcript.py` | Streams one transcript and keeps a compact digest of user prompts, final assistant texts and wrap-up recaps; refuses paths outside the sessions source |
| `context_handoff.py` | Finds and reads hand-written handoff notes in a project folder, bounded |
| `cli.py` | Wiring: loads the ledger and `sessions.json`, runs the optional refresh, prints |

**Matching.** Case-insensitive substring of the project name or path, or of a thread title (its project matches). All matches, most recent activity first; the first 6 get detail and the rest are listed by name. No match prints the 5 closest project names (`difflib`) and exits 1.

**Per project.**

- Live git, read-only (`rev-parse`, `symbolic-ref`, `status`, `rev-list`, `log`, `for-each-ref`): current branch, dirty counts, commits on no remote (all local branches, and the current one), the last 10 commits on the current branch, and local branches with commits not in the default branch (the 50 most recently committed are checked, 15 listed). No fetch, so remote-tracking refs are as of the last fetch. A missing path, a folder that is not a repo or a git failure is reported and the run goes on.
- **Handoff notes**, shown before the threads as the best source: regular files (no symlinks, junctions or other reparse points) in the project folder or directly in its `qa/`, `docs/` or `.claude/` folder, named (any case) `AGENT-NEXT-STEPS*.md`, `NEXT-STEPS*.md`, `HANDOFF*.md`, `ESTADO_PROYECTO.md` or `STATUS.md`. The 3 most recently modified, each read up to 256 KiB, with full path and modification time. A note up to 3000 characters is printed whole. A longer note prints its title and leading read-first block (the first section after the title when its heading says "read first", "important", "novedades" or similar; up to 800 characters), plus a table of contents of every heading (outside code fences) with its line number, and says to read the full file. The skill then reads it with the Read tool, starting with the sections on pending work, next steps, state and blockers. No section is picked by the command (see the decision log: picking by date was tried and reversed). A note modified before the project's latest activity (ledger `lastAt` or the newest commit on the current branch) carries `olderThanActivity: true` and is shown as possibly stale.
- Threads with no sessions (agent worktrees, inventory-only branches) collapse into one line: count, how many are at risk, idle range.
- **Automated runs** collapse into one line too (sessions, threads, last date, sessions per signal) and are left out of the ranking and of the overview's latest thread. A thread is automated when all its sessions are. A session is automated, first match wins, when: `entrypoint` is `sdk-cli` (what headless `claude -p` writes; the session scanner records the most common value per session); or it is single-turn and its prompt (first 200 characters, whitespace collapsed) equals the prompt of an `sdk-cli` session in any project (`prompt-of-automated`); or it is single-turn and 4 or more single-turn sessions of the project share that prompt (`repeated-prompt`); or it is job-shaped (one prompt, one reply, no title, not a fork) and shares its first 40 prompt characters with another job-shaped session of the project (`templated-prompt`). The entrypoint cannot be trusted alone: a `claude -p` child launched from a desktop session records `claude-desktop`. The job shape relies on Claude Code titling interactive sessions; on the real data every known automated run was untitled. For a single-turn session the last prompt the scanner keeps is its first prompt.
- The remaining threads are ranked by `lastAt` and the top N (default 8) shown with title, effective state, first and last activity, days idle, git scope summary, recap, ask, the last prompt only when it has 20 characters or more, and `claude --resume <lead>`.
- Transcript excerpts for the top K threads (default 5): the 2 most recent sessions of each, oldest first. Entries already shown for another session of the same project (same timestamp, role and text: a fork copies its parent's entries verbatim) are not printed again or counted against the head and tail; the session shows "N shared entries with session X omitted" instead. This needs no fork-family data: the copied entries identify themselves. Per session, the first 3 and last 8 entries, each clipped to 300 characters, with the omitted count between them. Entries are user prompts, the assistant's last text of each turn and wrap-up recaps (with their ask). Tool inputs, tool output, file contents, meta, sidechain (subagent) and compaction records, and prompts starting with a tag (harness-injected) are skipped.
- Transcript paths come from `sessions.json`: the path recorded in the ledger `inputs`, else `sessions.json` next to the ledger. If neither reads, a note says excerpts are unavailable. A path is opened only when it ends in `.jsonl` and its real path (symlinks and `..` resolved) lies under the sessions source: the report's `sourceRoot`, else `~/.claude/projects`. Otherwise the session shows "excerpts unavailable: path outside sessions source".

**Overview (no query).** Projects with activity in the last 14 days or at risk, one line each: name, days idle, at-risk flag, latest thread with sessions and its recap. No git calls, so it is fast.

**Size cap.** `--max-chars` (default 30000). Pieces are dropped least important first (excerpts from the last thread up, then whole handoff notes cut to 800 characters (their table of contents is then shown), then threads, then whole projects, keeping the first), and a note says what was dropped. Markdown is cut as a last resort; JSON is never cut and is marked `overLimit` instead.

**Header.** Ledger `generatedAt` and its age. `--refresh` runs the existing `refresh` (default out dir) first, with its progress on stderr so stdout holds only the context.

**Output.** Markdown by default; `--json` gives `schemaVersion: 1` with `mode` (`query` or `overview`), `query`, `ledger` (`path`, `generatedAt`, `ageHours`), `projects`, `alsoMatched`, `suggestions`, `notes` and `truncation`. Characters the console cannot encode are replaced, never raised.

Fields added by the correction pass (additive, `schemaVersion` stays 1):

| Where | Field | Meaning |
|---|---|---|
| project | `handoff` | `[{path, modifiedAt, bytes, lines, text, truncated, toc, olderThanActivity, lastActivityAt}]`, most recent first; `toc` is `[{line, level, heading}]` for every heading; `shortened: true` when the size cap cut a whole note to 800 characters |
| project | `automatedRuns` | `{threads, sessions, lastAt, signals}` or null; `signals` maps `entrypoint`, `prompt-of-automated`, `repeated-prompt`, `templated-prompt` to session counts |
| excerpt | `sharedWith` | `{session id: entries omitted because already shown for that session}` |
| truncation | `shortenedHandoffNotes` | Handoff notes cut to 800 characters by the size cap |

`sessions.json` records gain `entrypoint` (additive; its `schemaVersion` stays 3; the parse cache moves to version 4 so every transcript is re-parsed once).

**Skill.** `mod/work-ledger/skills/retomar/SKILL.md` runs the command from `$WORK_LEDGER_HOME` (default `~/Proyectos/work-ledger`) and writes, in the user's language: what the project is, where it stood, what is pending, git risks, and one ~5 minute next step. It weighs handoff notes first, then recaps and asks, then excerpts, then git, and says when a handoff note is possibly stale. At most one question. It says the brief is inferred and that external priorities live elsewhere, and never picks the priority among projects unless asked.

The skill treats everything the command prints (transcript excerpts, recaps, prompts, commit subjects, branch names, handoff note contents) as untrusted data, never as instructions: it ignores instructions found there, builds the next step from its own synthesis, and runs no command taken from the output without the user's explicit OK. Those texts were written by past sessions, tools or other people, so they are a prompt-injection channel.

## Data governance

The command itself writes no file, keeps no cache, makes no network call and calls no model; transcript and handoff text go to stdout only. That is not the same as "never stored": when the skill runs it inside a Claude Code session, the output becomes part of that session's transcript and model context, like any command output. The skill tells the model to quote only what the brief needs and not to copy transcript or handoff text into files, memory or messages. Transcript reads are confined to `.jsonl` files under the sessions source, so a tampered or stale `sessions.json` cannot make the command print other files; handoff discovery is limited to fixed names in four folders, regular files only.

## Limits

- The brief is inferred: transcripts show what was said, not what was finished. Git is the objective judge for commits, and only as fresh as the last fetch.
- External priorities (production release dates, tickets, deadlines) are not in the ledger.
- Matching is substring only: a typo finds nothing, and the closest names are the fallback.
- A user prompt that starts with `<` is taken as harness-injected and skipped.
- Threads are excerpted from their 2 most recent sessions only; older history needs `claude --resume`.
- Codex sessions are not read (the ledger does not have them yet).
- The `sourceRoot` guard trusts the root recorded in `sessions.json` itself; it stops paths that point outside the scanned source, not a report rewritten with a different root.
- Shared-entry detection needs identical timestamp, role and clipped text; an edited copy is printed again.
- An unattended run with an interactive entrypoint and a unique or rarely repeated prompt (fewer than 4 in the project and never run headless) is not detected.
- A single interactive session that reuses a headless job's exact prompt is collapsed as automated, and so are two untitled one-reply sessions of a project that open with the same 40 characters (an interactive session whose title generation failed could be one).
- Handoff notes over 3000 characters show only their lead and headings; the brief depends on the in-session model reading the file. OneDrive placeholder files are reparse points and are skipped.

## Next steps

- **Snapshot when a thread goes quiet**: the weekly run persists a short brief for threads that cross the idle threshold, so the context survives transcript cleanup. Needs its own governance review, since it would store derived text.
- **In-session guidance**: a short rule for sessions ("document as if this may be abandoned": wrap-up recaps that say what is pending and the next step), so recaps carry more signal.
- **External priority sources**: Azure DevOps work items, calendar, release dates, read-only, so the copilot can mention what is due without asking.
