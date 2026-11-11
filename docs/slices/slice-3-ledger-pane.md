# Slice 3: ledger pane in the Claude desktop app

## Goal

A compact, read-only pane beside the chat that answers "what is pending and where did I leave it" from `out/ledger.json`, without taking the whole screen. It is one adapter over the ledger; a tray app stays possible as another.

## Scope

- A Claude Code mod named `work-ledger`: `$.ui.open` pane, a `/ledger` slash command, a refresh action.
- Reads `ledger.json` with `$.fs.read` (about 250 KB today; the API limit is 4 MiB). Never reads transcripts or repos itself.
- Writes nothing except by running the CLI's `refresh`, which writes only under `work-ledger/out/`.
- Overrides (marking threads done, paused, merged) are out of scope for this slice; the pane only shows them.

## Options (`userConfig`)

| Option | Default | Use |
|---|---|---|
| `ledgerPath` | `~/Proyectos/work-ledger/out/ledger.json` | File the pane reads |
| `projectRoot` | `~/Proyectos/work-ledger` | `cwd` for refresh |
| `pythonCommand` | `python` | Executable for refresh |
| `openOnStart` | `false` | Open the pane at session start |
| `piecesDir` | `~/Proyectos/work-ledger/out/pieces/inbox` | Curation inbox |

A leading `~` in a path option is the home dir, read at runtime with `$.env.get` (`USERPROFILE`, else `HOME`). The mod API has no home-dir call; `$.env.get` reads the environment without starting a process. When neither variable is set the path is used as written and the read fails naming it.

No secrets are involved.

## Layout (top to bottom)

1. **Header**: ledger age ("updated 3 h ago"), counts (projects at risk, threads at risk, open), a **Refresh** button.
2. **At risk, recent**: threads with effective state `at-risk` and `recency: recent`. One line each: project name, title, days idle, git risk and `notOnRemote`.
3. **Projects at risk**: project name, main worktree risk, `notOnRemote`, days idle. Older at-risk threads are counted here per project, not listed.
4. **Open**: threads with effective state `open` or `active`, most recent first, at most 15.
5. **By project**: one collapsed row per project with counts per effective state; expanding shows its threads. Stale, likely-done and done threads appear only here.

Selecting a thread shows its detail in place: title, project, key, state and reason, `lastAt`, lead recap, ask and last prompt, session ids with the lead first, the command `claude --resume <lead session id>`, and related threads (fork family). A back control returns to the list.

The pane fits the viewport: lists are truncated to the rows available with a "+N more" line.

## Refresh

`$.process.run([pythonCommand, "-m", "work_ledger", "refresh"], { cwd: projectRoot, env: { PYTHONPATH: "src" }, timeoutMs: 600000 })`. While running, the button shows "Refreshing…" and is disabled. On exit 0 the ledger is re-read and a toast says so; otherwise a toast shows the exit code and the last stderr line. A refresh takes about 2.5 min with a cold session cache.

## Errors

- Missing or unreadable ledger: the pane says so and offers Refresh.
- Unknown `schemaVersion` (not 2): the pane says the ledger is from an unsupported version.
- Malformed JSON: the pane shows the parse error message, not a crash.

## State

Pane state lives in `$.state` atoms declared in `types/index.d.ts`: the parsed view model, the selected thread id, expanded project ids, refresh status. Each atom has a `shape` tag so a reload with changed fields discards old values.

## Engineering constraints

- Parsing the ledger into a view model is a pure function, tested with `claude plugin test` and synthetic ledger fixtures.
- `claude plugin validate` and `tsc -p` must pass.
- No emails, message text or file contents beyond what `ledger.json` already holds.
- The mod source is written to the session's dev-mods folder for hot reload and copied to `work-ledger/mod/work-ledger/` as the versioned source.
