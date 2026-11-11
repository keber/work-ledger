# Slice 2: thread builder (the ledger)

## Goal

Join the git inventory (slice 0) and the session facts (slice 1) into `ledger.json`: one record per work thread with its sessions, git state, last activity, how it ended, and a suggested state. This is the contract every view reads.

## Inputs

- `out/git-inventory.json` (schemaVersion 2)
- `out/sessions.json` (schemaVersion 2)
- `overrides.json` (optional, user-owned, at the project root by default; never written by the tool)

The builder is pure over these files: no git calls, no transcript reads. Unknown schema versions fail with a clear message.

## Fix carried from slice 1: temp paths

Writes under a temp directory are excluded from `writeAnchor` in the session scanner. A path is temp when, case-insensitively and after normalization, it starts with `tempfile.gettempdir()` or contains `/appdata/local/temp/`. The second rule covers 8.3 short names (for example `JOHNDO~1`) that differ from the long form. If every write is temp, `writeAnchor` is `null`. Bump sessions schemaVersion to 3 and accept 3 in the builder.

## Thread identity

For each session, the **anchor path** is `writeAnchor.path`, else its most frequent `cwd` (or `relocatedCwd` when present).

Resolve the anchor path against the inventory, longest worktree path that is a prefix of it (case-insensitive, forward slashes):

| Case | Thread key | kind |
|---|---|---|
| Inside a worktree on a branch | `git:<main worktree path>#<branch>` | `git` |
| Inside a detached worktree | `git:<main worktree path>@<worktree path>` | `git` |
| Not in any inventoried worktree, session wrote files | `dir:<anchor path>` | `dir` |
| Not in any worktree, no writes | `session:<sessionId>` | `session` |

The last row keeps exploratory sessions in a catch-all folder (`ClaudeSession`) from collapsing into one giant thread. The user merges them through overrides.

Thread `id`: first 12 hex characters of SHA-256 of the key. Stable across runs.

### Inventory-only threads

Worktrees and branches with risk `modified`, `unpushed` or `untracked` that no session resolves to become threads with no sessions (`origin: "inventory"`). These are at-risk work with no known session, such as leftover subagent worktrees. Items with other risks do not create threads.

## Thread record

- `id`, `key`, `kind`, `origin` (`sessions` or `inventory`).
- `title`: title of the most recent session that has one; else the branch name; else the last path segment of the key.
- `domain`: `work` for now. The field exists so personal sources can be added without a schema change.
- `sessions`: sessionIds sorted by `lastAt` descending; `sessionCount`.
- `lead`: the session with the latest `lastAt`. Its `lastRecap`, `lastAsk` and `lastPrompt` are copied as `resume`.
- `firstAt`, `lastAt`, `daysIdle` (whole days from `lastAt` to `generatedAt`).
- `git` (kind `git` only): `repo`, `branch`, `worktreePath`, `risk`, `notOnRemote`, `dirty`, `merged`, `found` (false when the branch or worktree is not in the inventory anymore).
- `gitActions`: summed over sessions.
- `related`: other thread ids sharing a fork family with any session of this thread, with `sharedMessages` (max) and `reason: "fork-family"`.
- `suggestedState` and `suggestedReason`.
- `state`: the override state if present, else `null`. `effectiveState` = `state` ?? `suggestedState`.

## Suggested state (first match wins)

| suggestedState | Condition |
|---|---|
| `at-risk` | git risk `modified`, `unpushed` or `untracked` |
| `waiting-merge` | git risk `pushed` |
| `likely-done` | git risk `safe`; or kind not `git`, lead has a `lastRecap`, no `lastAsk`, and `daysIdle` ≥ 7 |
| `stale` | `daysIdle` ≥ 30 |
| `open` | otherwise |

`git.found = false` counts as no git risk. `daysIdle` is reported for every state, so an `at-risk` thread untouched for months is visible as such.

## Overrides

```json
{
  "schemaVersion": 1,
  "threads": {
    "<threadId>": { "state": "active|paused|discarded|done", "note": "..." }
  },
  "merge": [ { "into": "<threadId>", "from": ["<threadId>", "..."] } ]
}
```

- `merge` moves the sessions of `from` threads into `into`; `from` threads disappear. Merges are applied before states. A merge naming an unknown id is reported as a warning, not an error.
- Override states are the user's vocabulary; suggested states are the tool's. Both are kept.

## Output

- `out/ledger.json`: `schemaVersion: 1`, `generatedAt`, `inputs` (paths and their `generatedAt`), `warnings`, `stats` (counts per kind and per effective state), `threads[]` sorted by effective state order (`at-risk`, `open`, `waiting-merge`, `active`, `paused`, `stale`, `likely-done`, `done`, `discarded`) then `lastAt` descending.
- `out/ledger.md`: one section per effective state, one line per thread: title, short key, last activity and days idle, git risk and `notOnRemote`, session count, lead recap (first 120 characters).

## CLI

- `python -m work_ledger threads [--inventory PATH] [--sessions PATH] [--overrides PATH] [--out DIR]`
- `python -m work_ledger refresh [--out DIR]`: runs `inventory`, `sessions` and `threads` in order with default arguments; stops at the first failure with its exit code.

## Engineering constraints

Same as previous slices: Python 3.14 stdlib, `unittest`, strict TDD, synthetic fixtures only (no test reads real `out/` files, `~/.claude` or repos). Identity resolution, state suggestion, override application and rendering are separate pure functions.

## First real run (2026-11-04)

`refresh` end to end in 91 s (inventory dominates; sessions mostly cached). 256 tests passing. 88 threads: git 61, dir 5, session 22. Effective states: at-risk 42, open 10, stale 20, likely-done 16. No warnings.

### Findings

1. **Repo + branch is too coarse for trunk-based repos.** `<repo QA A>#master` collected 78 sessions: most QA work there happens directly on `master`. The thread title comes from the latest session (session S5), which misrepresents the other 77. The user's QA repos are mostly trunk-based, so this is the common case, not an edge case.
2. **Git Bash paths are not normalized.** A write recorded as `/c/Users/...` produced `dir:/c/Users/...` instead of joining the repo thread.
3. **Inventory-only titles lack the repo.** Threads titled `main` or `master` are ambiguous; the title needs the repo name.
4. **At-risk is dominated by old dirty main worktrees** of team repos (100 to 430 days idle). Correct, but the view needs to separate recent at-risk work from old residue.
5. **Correct cases**: this design session resolved to `work-ledger` despite running in `ClaudeSession`; the LaTeX skill session resolved to `~/.claude/skills/latex-pdf`; tool repo A shows 19 commits on no remote.

## Model change: projects and threads (approved 2026-11-05)

Two levels: a **project** (repo or directory) groups **threads**. Ledger `schemaVersion` becomes 2.

### Project identity

| Session resolves to | Project key | Project kind |
|---|---|---|
| Any worktree of a repo | `repo:<main worktree path>` | `repo` |
| `dir:<anchor>` thread | `dir:<anchor path>` | `dir` |
| `session:<id>` thread | `dir:<most frequent cwd>` (or `relocatedCwd`) | `dir` |

Project `id`: first 12 hex characters of SHA-256 of the project key. `name`: last path segment.

### Thread identity (replaces the first table row)

The repo's default branch is the inventory's `defaultBranch` for that repo.

| Case | Thread key |
|---|---|
| Worktree on a branch that is not the default branch, or the repo has no default branch | `git:<main>#<branch>` (unchanged) |
| Worktree on the default branch, session in a fork family | `git:<main>#<branch>~family:<familyId>` |
| Worktree on the default branch, no fork family | `git:<main>#<branch>~session:<sessionId>` |
| Detached worktree, `dir`, `session` | unchanged |

Fork family members that resolve to different projects or branches stay in different threads, linked through `related`.

### Git scope

- Feature-branch and detached threads keep `git` as today; `gitScope: "thread"`.
- Default-branch threads get `gitScope: "project"` and `git: null`. Their suggested state ignores git risk: the shared working tree cannot be attributed to one session.
- The **project** carries the main worktree state: `git` with `defaultBranch`, `branch`, `worktreePath`, `risk`, `notOnRemote`, `dirty`, `lastCommit` (no emails).

### Project record

`id`, `key`, `kind`, `name`, `path`, `domain`, `git` (repo projects only, else `null`), `threadIds`, `threadCount`, `sessionCount`, `lastAt`, `daysIdle` (from the latest thread; inventory-only projects use `lastCommit` date, else `null`), `atRisk` (main worktree risk is `modified`, `unpushed` or `untracked`, or any thread is `at-risk`).

### Inventory-only items

- Non-main worktrees and branches at risk with no session: inventory-only threads as before. Title: `<repo name> · <branch>` (detached: `<repo name> · <worktree folder name>`).
- A main worktree at risk is project-level risk, not a thread. A repo with no sessions and an at-risk main worktree still produces a project with zero threads.

### Path normalization

Git Bash paths `/<letter>/...` become `<LETTER>:/...` in the session scanner (writes, cwds, `relocatedCwd`) before anchor resolution. Session cache version bumps to 3 so cached entries are re-parsed. The builder applies the same normalization defensively before prefix matching.

### Recency

Every thread and project gets `recency`: `recent` when `daysIdle` < 30, else `old` (`null` daysIdle counts as `old`). The suggested state does not change.

### Output changes

- `ledger.json`: adds `projects[]` (sorted: `atRisk` first, then `lastAt` descending) and `stats.projects`; threads gain `projectId`, `gitScope`, `recency`.
- `ledger.md`: first section **Projects at risk** (project name, main worktree risk and `notOnRemote`, at-risk thread count, days idle). Thread sections as before with the project name prefixed, and the `at-risk` section split into **recent** and **older than 30 days**.
- Overrides schema unchanged; `threads` and `merge` still address thread ids. Thread ids of default-branch threads change, which is acceptable because no overrides exist yet.

## Second real run (2026-11-05, ledger schemaVersion 2)

303 tests passing. `refresh` in 150 s (sessions fully re-parsed after the cache bump). 29 projects (23 at risk), 146 threads: at-risk 21, open 35, stale 73, likely-done 17. All 147 sessions are assigned.

- **Trunk repos split.** Repo QA A went from one 79-session thread to 88 threads in one project: 74 on `master` (4 fork families, 54 stale, 20 open) plus feature-branch and inventory-only threads. The largest thread now has 6 sessions.
- **Bug found on the run:** the inventory stores `defaultBranch` as a remote-tracking name (`origin/master`), so no session matched the default branch. The builder now compares against the short name, stripping a leading `origin/`. Remotes with other names are not handled until the inventory records remote names.
- **No `/c/...` keys remain.** At-risk threads: 9 recent, 12 older than 30 days.
- **Next concern for the view:** 73 stale threads, mostly single trunk sessions. The pane needs to collapse stale threads per project and lead with recent and at-risk work.
