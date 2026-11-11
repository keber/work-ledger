# work-ledger

Personal tool to reduce dispersion and context-switching cost: see what I have been working on (Claude Code, Codex), whether each piece of work is finished or pending, resume it quickly, get periodic reminders of stalled work, and receive curated drafts of communication pieces about that work.

**Status**: slice 0 (git inventory), slice 1 (session scanner), slice 2 (thread builder), slice 4 (weekly digest) and slice 5 (weekly curation, CLI only; the pane section is pending) implemented; see [docs/slices/slice-0-git-inventory.md](docs/slices/slice-0-git-inventory.md), [docs/slices/slice-1-session-scanner.md](docs/slices/slice-1-session-scanner.md), [docs/slices/slice-2-thread-builder.md](docs/slices/slice-2-thread-builder.md) [docs/slices/slice-4-weekly-digest.md](docs/slices/slice-4-weekly-digest.md) and [docs/slices/slice-5-weekly-curation.md](docs/slices/slice-5-weekly-curation.md).

## Documents

| Document | What it holds |
|---|---|
| [docs/01-problem-and-goals.md](docs/01-problem-and-goals.md) | The problem, desired capabilities, non-goals |
| [docs/02-architecture.md](docs/02-architecture.md) | Three-layer architecture, data sources, platform constraints |
| [docs/03-work-thread-model.md](docs/03-work-thread-model.md) | What a "work thread" is and how sessions are grouped into threads |
| [docs/04-evidence-swot-session.md](docs/04-evidence-swot-session.md) | Findings from the 2026-10-27 SWOT session and their design implications |
| [docs/decision-log.md](docs/decision-log.md) | Decisions taken, with date and rationale |
| [docs/open-questions.md](docs/open-questions.md) | What is still undecided or unverified |

## Language

Artifacts are written in English (team default for technical artifacts). Discussion with the user happens in Spanish.

## Run

Requires Python 3.14 and git on `PATH`. Standard library only, no install needed.

| Task | Command (from the project root, Git Bash) |
|---|---|
| Git inventory, default roots (`[inventory] roots`, else `~/Proyectos`, `~/source/repos`) | `PYTHONPATH=src python -m work_ledger inventory` |
| Custom roots (repeatable) and output dir | `PYTHONPATH=src python -m work_ledger inventory --root ~/Proyectos --out out` |
| Extra untracked prefixes to count apart (repeatable, added to defaults `.atl/`, `.tmp/`) | `PYTHONPATH=src python -m work_ledger inventory --ignore-untracked reference/` |
| Claude Code sessions, default source (`~/.claude/projects`), incremental | `PYTHONPATH=src python -m work_ledger sessions` |
| Sessions from another source, re-parsing every transcript (ignore cache) | `PYTHONPATH=src python -m work_ledger sessions --source DIR --out out --full` |
| Work threads (ledger) from `out/` inputs and `overrides.json` at the project root | `PYTHONPATH=src python -m work_ledger threads` |
| Ledger from explicit inputs | `PYTHONPATH=src python -m work_ledger threads --inventory PATH --sessions PATH --overrides PATH --out out` |
| Inventory, sessions and threads in order, stopping at the first failure | `PYTHONPATH=src python -m work_ledger refresh` |
| Weekly digest: refresh, then write `out/digest/YYYY-MM-DD.md` and `latest.json` (`--no-refresh` reuses the ledger; also `--ledger PATH`, `--out DIR`) | `PYTHONPATH=src python -m work_ledger digest` |
| Windows toast for the latest digest; clicking it opens the Markdown (`--digest PATH` for another `latest.json`) | `PYTHONPATH=src python -m work_ledger notify` |
| Draft communication pieces for every audience with Claude Code (`--audience portfolio team public` to pick, `--claude PATH`, `--ledger PATH`, `--out DIR`) | `PYTHONPATH=src python -m work_ledger curate` |
| Write the model input per audience to the inbox, no model call | `PYTHONPATH=src python -m work_ledger curate --dry-run` |
| List pieces, newest inbox first (`--status proposed\|approved\|discarded`) | `PYTHONPATH=src python -m work_ledger pieces list` |
| Approve a piece and copy it to the publish dir (`--publish-dir DIR` or `WORK_LEDGER_PUBLISH_DIR`) | `PYTHONPATH=src python -m work_ledger pieces approve 2026-11-12-team-1` |
| Discard a piece | `PYTHONPATH=src python -m work_ledger pieces discard 2026-11-12-team-1` |
| Digest, curate, then toast (what the scheduled task runs) | `PYTHONPATH=src python -m work_ledger weekly` |
| Tests | `python -m unittest discover -s tests -t .` |

Output goes to `out/git-inventory.json` (`schemaVersion: 2`) and `out/git-inventory.md`. The scan is read-only: it never fetches, prunes, checks out or writes inside a repo, so remote-tracking refs may be stale (see each repo's last fetch time). Untracked paths under an ignored prefix are reported as `dirty.ignoredUntracked` and never make an item `untracked`; prefixes match the path git prints, with forward slashes, from the worktree root.

The sessions scan writes `out/sessions.json` (`schemaVersion: 3`) and `out/sessions.md`, and keeps a parse cache in `out/.cache/sessions-cache.json` (unchanged transcripts, by size and mtime, are not re-parsed). It is read-only on the source and stores no message text, tool output or file content; only the last wrap-up recap/ask (300 chars) and last prompt (200 chars) are kept. Git actions are detected by regex over shell commands, so a command quoted inside another (`echo "git push"`) still counts. Writes under the temp directory (`tempfile.gettempdir()` or any `/AppData/Local/Temp/`) do not count for `writeAnchor`.

The thread builder writes `out/ledger.json` (`schemaVersion: 2`) and `out/ledger.md`: projects (repo or directory, with the main worktree git state) grouping work threads, one record per thread with its sessions, git state, resume text, recency and a suggested state. Work on a repo's default branch is split into one thread per fork family or session. `ledger.md` opens with the projects at risk and splits at-risk threads into recent and older than 30 days. It reads only the two JSON inputs and the optional `overrides.json` (user-owned, never written by the tool); unknown input schema versions exit with code 1.

The weekly digest reads `out/ledger.json` (`schemaVersion: 2`) and the previous `out/digest/latest.json`. It lists recent at-risk threads, commits on no remote, open or active threads idle 7 days or more (with their `claude --resume` command), threads that went stale since the previous digest, and state totals with their change. Threads overridden as `done`, `discarded` or `paused` are left out of the lists but not out of the backup check. A second run on the same day overwrites that day's file and compares against the earlier run. `notify` runs Windows PowerShell with a fixed script and passes the toast XML through an environment variable, never inside the script text. Off Windows, or when the toast fails or takes over 30 s, it prints the summary and exits 1.

The digest also keeps the `latest.json` it replaces as `out/digest/previous.json`, so curation can compare against the digest before the one `weekly` just wrote.

## Configuration

Settings that name your company or your own folders live in `work-ledger.local.toml` at the project root. That file is gitignored; the tracked template is `work-ledger.example.toml` (neutral values). Start from it:

```sh
cp work-ledger.example.toml work-ledger.local.toml
```

Another file can be used with `--config PATH` (on any command) or `WORK_LEDGER_CONFIG`. A file named that way must exist; the default file may be missing, and then built-in defaults apply. Invalid TOML, a wrong type or an unknown key exits with code 2.

Each setting resolves as **CLI flag > environment variable > config file > built-in default**. Every path may start with `~` and is expanded.

| Key | CLI flag | Environment variable | Built-in default |
|---|---|---|---|
| `[curation] company_terms` (list) | `--company TERM` (repeatable) | `WORK_LEDGER_COMPANY_TERMS` (comma-separated) | none: the public check has no company rule, and `curate` and `pieces approve` print a warning |
| `[curation] publish_dir` | `--publish-dir DIR` | `WORK_LEDGER_PUBLISH_DIR` | `~/Documents/work-ledger/published` |
| `[curation] claude` (optional) | `--claude PATH` | `WORK_LEDGER_CLAUDE` | `claude.exe`, else `claude`, on `PATH` |
| `[inventory] roots` (list) | `--root PATH` (repeatable) | `WORK_LEDGER_ROOTS` (`os.pathsep`-separated) | `~/Proyectos`, `~/source/repos` |

The tests never read `work-ledger.local.toml`: `tests/__init__.py` points `WORK_LEDGER_CONFIG` at an empty file.

## Curation

`curate` drafts a few short pieces about the week's work, one set per audience, and leaves them for you to approve or discard. Nothing is posted anywhere.

| Audience | Reader | Visibility | Kept per run |
|---|---|---|---|
| `portfolio` | Manager and other team leads | internal | 2 |
| `team` | The team | internal | 2 |
| `public` | Personal blog or LinkedIn | external | 1 |

- **Input.** Threads of `out/ledger.json` active in the 7 days before the ledger `generatedAt`, plus threads whose effective state changed since the previous digest; `discarded` threads are left out. Only id, title, project name, effective state, first and last activity, session count, git action counts and the lead recap and ask are sent: no paths, keys, session ids, branches or prompts. The input is capped at 60 threads and 40,000 characters, dropping the oldest; the run records how many were dropped.
- **Model call.** One `claude -p` call per audience (`--model claude-opus-5-5 --output-format json --json-schema ... --tools "" --strict-mcp-config --restricted --no-session-persistence --system-prompt ...`), input on stdin, 5 minute timeout, run from an empty temporary directory. It uses your Claude Code sign-in; the project handles no API key. Without `--claude PATH`, `WORK_LEDGER_CLAUDE` or `[curation] claude`, `claude.exe` on `PATH` is used, else `claude`. Batch wrappers (`claude.cmd` from npm) are never run, because cmd.exe cannot pass the multi-line prompt safely: the native binary the npm package installs beside the wrapper (`node_modules/@anthropic-ai/claude-code/bin/claude.exe`) is used instead, and when it is missing `curate` stops and asks for `--claude`. The prompts are in `src/work_ledger/prompts/` and ask for neutral, professional Spanish.
- **Untrusted output.** The result is validated against the schema in Python. A failed call, a timeout, invalid JSON, a schema mismatch or `is_error` skips that audience with a warning; the others still run and `curate` exits 1. Candidates citing a thread that was not in the input are discarded; the most relevant ones are kept up to the audience maximum. Slugs and paths are built from the date, the audience id and a number, never from model text.
- **Public check.** A `public` candidate is rejected when its title, summary, body or rationale contains a project, repo or worktree folder name from the ledger and inventory (whole words, three characters or more), a company name or domain from the configuration (see [Configuration](#configuration); `curate` warns when none is set), an email, URL, Windows or POSIX path, IP address, a ticket-like id (`#123`, `AB#123`, `PBI 123`, `ABC-123`), or a term from `curation-denylist.txt` at the project root (yours, gitignored, one term per line, `#` for comments; `--denylist PATH` for another file). Rejections record the rule name, never the matched text. **Passing the check is not proof of safety**: read every public piece before approving it.

### Approval and the publish dir

Proposals land in `out/pieces/inbox/<YYYY-MM-DD>/<audience>-<n>.md`. Edit a file freely before approving it: approval copies its current text. A second run on the same day adds new numbers and never overwrites a file.

- `pieces approve <id>` sets `status: approved` and copies the file to `<publishDir>/<audience>/<YYYY-MM-DD>-<slug>.md` (a `-2` suffix when the name exists). `publishDir` is `--publish-dir`, else `WORK_LEDGER_PUBLISH_DIR`, else `[curation] publish_dir`, else `~/Documents/work-ledger/published`. Approving a `public` piece re-runs the check on the edited file and refuses if it fails, or if `out/ledger.json` cannot be read (the names to check come from it).
- `pieces discard <id>` sets `status: discarded`. Only `proposed` pieces can be approved or discarded.

### File contract (read by the ledger pane)

Front matter: the lines between the first two `---` lines, one `key: value` per line, each value JSON-encoded (also valid YAML), in this order: `id` (`<date>-<audience>-<n>`), `audience`, `visibility` (`internal` or `external`), `status` (`proposed`, `approved`, `discarded`), `title`, `summary`, `sourceThreadIds`, `relevance` (0..1), `rationale`, `generatedAt`, `model`. The body is `# <title>` and the Markdown text.

`out/pieces/inbox/<date>/index.json` (`schemaVersion: 1`): `date`, `updatedAt`, `pieces[]` and `runs[]`. The latest inbox is the newest date folder.

- Each `pieces[]` entry holds the front matter fields plus `file` (name in the same folder), `sourceThreads` (`[{id, title, project}]` from the ledger), `publishedPath` and `decidedAt` (both `null` until approved or discarded). `approve` and `discard` update `status` there too.
- Each `runs[]` entry holds `generatedAt`, `ledgerGeneratedAt`, `previousDigestGeneratedAt`, `model`, `input` (`threads`, `droppedByCap`, `chars`) and `audiences`: per audience `status` (`ok` or `failed`), `warnings`, `candidates`, `kept` (piece ids), `rejected` (`[{candidate, reason, rules}]`, reason `unknown-source-thread`, `sanitization` or `over-limit`) and `input`.

`weekly` runs `digest`, then `curate`, then `notify`; the toast adds the number of new pieces to review. A failing or crashing `curate` does not stop the toast; `weekly` then exits non-zero.

## Weekly task

`scripts/install-weekly-task.ps1` registers the per-user task `\WorkLedger\WeeklyDigest`: weekly trigger, a missed start runs when the machine is back on (`StartWhenAvailable`), only while you are logged on, no stored password, no elevation. The task runs `scripts/weekly.cmd`, which moves to the project root, sets `PYTHONPATH=src`, runs `python -m work_ledger weekly` (digest, curate, toast) and appends its output to `out/weekly.log`. Re-running the install replaces the task. Installing changes persistent system configuration, so preview it with `-WhatIf` first.

| Task | Command (from the project root, PowerShell) |
|---|---|
| Preview the install | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-weekly-task.ps1 -Day Monday -Time 09:00 -WhatIf` |
| Install (`-Python` takes a name or path, default `python` resolved on `PATH` at install time) | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-weekly-task.ps1 -Day Monday -Time 09:00` |
| Uninstall | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall-weekly-task.ps1` |

`-ExecutionPolicy Bypass` applies only to that PowerShell process; drop it if your policy already allows local scripts.
