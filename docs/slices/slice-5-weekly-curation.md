# Slice 5: weekly curation of communication pieces

## Goal

Every Thursday, after the digest, draft a few short communication pieces about the week's work, one set per audience, and leave them for the user to approve or discard. Approved pieces are copied to a local publication folder. Nothing is posted anywhere automatically.

## Audiences

| Audience id | Reader | Visibility | Max pieces per week |
|---|---|---|---|
| `portfolio` | The user's manager and other team leads | internal | 2 |
| `team` | The team: cumulative progress of what was built or done | internal | 2 |
| `public` | Personal blog or LinkedIn | external | 1 |

## Input to the model

Only fields already in `out/ledger.json` (schemaVersion 2), for threads whose `lastAt` falls in the last 7 days, plus threads that changed effective state since the previous digest snapshot:

- thread `id`, `title`, project `name`, `effectiveState`, `firstAt`, `lastAt`, `sessionCount`, `gitActions` counts, lead `lastRecap` and `lastAsk`.
- No paths, keys, session ids, branch names, emails, prompts or transcript text.

Threads in effective state `discarded` are excluded. The input is capped at 60 threads (most recent first) and 40,000 characters; the run records how many threads were dropped by the cap.

All current data is the **work** domain. Personal or academic sources do not exist yet; when they do, they must never be mixed into the same model call.

## Generation

One call per audience to Claude Code in headless mode, so no API key is handled by this project:

```
claude -p --model claude-opus-5-5 --output-format json --json-schema <schema>
       --tools "" --strict-mcp-config --restricted --no-session-persistence
       --system-prompt <audience prompt>
```

- The input goes on stdin. No tools and no MCP servers, so the model cannot read files or reach the network.
- `--no-session-persistence` keeps these runs out of `~/.claude/projects`, so the session scanner never ingests them.
- `--bare` is not used: it accepts only `ANTHROPIC_API_KEY`, and the user signs in with OAuth.
- Schema: `{ pieces: [{ title, summary (≤ 300 chars), body (Markdown, ≤ 2,500 chars), sourceThreadIds[], relevance (0..1), rationale (≤ 200 chars) }] }`, at most 4 candidates.
- The tool keeps the top candidates by `relevance` up to the audience maximum, and discards any whose `sourceThreadIds` are not in the input.
- Timeout 5 min per call. A failed call (non-zero exit, timeout, invalid JSON, schema mismatch, the `is_error` field in the JSON result) skips that audience with a warning; other audiences still run.

Audience prompts live in `src/work_ledger/prompts/<audience>.md`, in English, and ask for Spanish output (neutral, professional) because the readers are Spanish-speaking. They tell the model to use only the given facts, not to invent results or metrics, and to say what was done, why it matters and what is next.

## Sanitization for external pieces

`public` pieces must not reveal internal details. Before a `public` candidate is kept, a deterministic check rejects it if its title, summary or body contains:

- any project name, repo name or worktree folder name from the ledger and inventory, case-insensitive;
- the company name or its domain (`[curation] company_terms` in the gitignored `work-ledger.local.toml`, `WORK_LEDGER_COMPANY_TERMS` or `--company`; no built-in terms, and `curate` warns when none is configured);
- emails, URLs, Windows or POSIX paths, IP addresses, or ticket-like ids (`#123`, `AB#123`, `PBI 123`);
- terms from a user-owned denylist file `curation-denylist.txt` at the project root (gitignored, one term per line).

The `public` prompt also asks for lessons and techniques, not systems or clients. A rejected candidate is recorded with the matched rule, not the matched text. Passing the check is not proof of safety: every public piece still needs the user's approval, and the approval screen says so.

## Proposals and approval

- Proposals are written to `out/pieces/inbox/<YYYY-MM-DD>/<audience>-<n>.md` with front matter: `id` (`<date>-<audience>-<n>`), `audience`, `visibility`, `status: proposed`, `sourceThreadIds`, `relevance`, `rationale`, `generatedAt`, `model`.
- `out/pieces/inbox/<date>/index.json` lists them.
- `python -m work_ledger pieces list [--status proposed]` prints them.
- `python -m work_ledger pieces approve <id>` sets `status: approved` and copies the file to `<publishDir>/<audience>/<YYYY-MM-DD>-<slug>.md`. Default `publishDir`: `~/Documents/work-ledger/published`, configurable with `--publish-dir` or the `WORK_LEDGER_PUBLISH_DIR` environment variable.
- `python -m work_ledger pieces discard <id>` sets `status: discarded`.
- Approving a `public` piece re-runs the sanitization check, and refuses if it fails (the user may have edited the file).
- The user can edit a proposal file before approving it; approval copies the current text.

## CLI and schedule

- `python -m work_ledger curate [--ledger PATH] [--out DIR] [--audience ID ...] [--claude PATH] [--dry-run]`. `--dry-run` writes the model input per audience to `out/pieces/inbox/<date>/input-<audience>.json` and makes no model call.
- `weekly` runs `digest`, then `curate`, then `notify`. The toast adds the number of proposals. A failed `curate` does not stop `notify`.
- The Thursday task stays as installed. It runs `weekly`, so no change to Task Scheduler is needed.

## Pane

The ledger pane adds a **Pieces to review** section above the thread lists when the latest inbox has proposed pieces: audience, title, relevance. Selecting one shows the summary, rationale and source thread titles, with **Approve** and **Discard** buttons that run the CLI through a `$.clock.after` timer, as Refresh does. Public pieces show the warning "Check it for internal details before approving."

## Engineering constraints

- Python 3.14 stdlib and `unittest`, strict TDD, synthetic fixtures only.
- Input selection, sanitization, candidate selection and file writing are pure or port-based. The `claude` call sits behind a port, so tests never run it.
- Model output is untrusted data: it is validated against the schema and never executed or used in a path. Slugs are derived and filtered to `[a-z0-9-]`.
- Mod changes follow slice 3 (validate, type check, plugin tests).

## Implementation notes (2026-11-10, CLI only)

The pane section is not implemented yet. The file contract it will read (front matter and `index.json`) is documented in the README, section **Curation**.

Interpretations taken while implementing:

- **Previous digest.** `weekly` writes the digest just before `curate`, so `latest.json` already holds this week's snapshot. The digest now keeps the file it replaces as `out/digest/previous.json`. Curation compares against `latest.json` when it was built from another ledger, else against `previous.json`. A thread absent from the snapshot counts as unchanged; it is still selected when it is recent.
- **Seven days** count back from the ledger `generatedAt`. A thread with no `domain` counts as `work`.
- **Schema.** `title` has no limit in the spec; it is capped at 160 characters. Strings must be non-empty and `sourceThreadIds` must have at least one id.
- **Public check** also covers `rationale`, because the rationale is copied into the published file's front matter. Auto-derived project names shorter than three characters are ignored, and they match as whole words, with `-`, `_`, `.` or spaces between their parts. Company and denylist terms match as substrings. Accents are folded before matching. Jira-style keys (`ABC-123`) count as ticket ids.
- **Same-day reruns** append new numbers and never overwrite or delete a proposal, so edits are never lost.
- **Exit codes.** `curate` exits 1 when any audience failed, after it writes the others. `weekly` returns the digest's code when the digest fails. Otherwise it returns notify's code, or curate's code when notify succeeds.
- **`claude.cmd`** (the npm wrapper) is never run, because cmd.exe re-parses the arguments and cannot carry the multi-line system prompt. The resolver prefers `claude.exe` on `PATH`. It replaces a wrapper with the native binary that npm installs beside it, `<wrapper dir>/node_modules/@anthropic-ai/claude-code/bin/claude.exe`. If that binary is missing, it refuses and asks for `--claude`.
