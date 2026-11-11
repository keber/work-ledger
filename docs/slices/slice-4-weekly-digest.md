# Slice 4: weekly pending-work digest and reminder

## Goal

Once a week, refresh the ledger, write a short digest of work left pending, and show a Windows notification that opens it. The user changed the cadence from 15 days to **weekly** (2026-11-06).

The job runs outside the Claude app: mod timers die with the session, so scheduling belongs to Windows Task Scheduler.

## Digest content

Computed from `out/ledger.json` (schemaVersion 2) and the previous digest snapshot, if any:

1. **At risk, recent**: threads `at-risk` with `recency: recent`. Title, project, days idle, git risk, `notOnRemote`.
2. **No backup**: projects whose main worktree has `notOnRemote > 0`, and threads with `notOnRemote > 0`. Sum of commits on no remote.
3. **Going cold**: threads in effective state `open` or `active` with `daysIdle` ≥ 7. For each: lead recap (first 160 characters), lead ask, and `claude --resume <lead session id>`.
4. **Went stale this week**: threads stale now that were not stale (or did not exist) in the previous snapshot. Title and project only.
5. **Counts**: older at-risk threads per project (not listed), and totals per effective state with the change since the previous digest.

Threads with an override state `done`, `discarded` or `paused` are excluded from sections 1, 3 and 4.

The digest stores no data beyond what `ledger.json` already holds.

## Outputs

- `out/digest/YYYY-MM-DD.md`: the digest, Markdown, newest first sections as above, with the ledger `generatedAt`.
- `out/digest/latest.json`: `schemaVersion: 1`, `generatedAt`, `ledgerGeneratedAt`, `path` of the Markdown, `counts`, and a `snapshot` of `{threadId: effectiveState}` used by the next run.
- Running twice on the same day overwrites that day's file. The previous snapshot is read before `latest.json` is overwritten.

## CLI

- `python -m work_ledger digest [--ledger PATH] [--out DIR] [--no-refresh]`: by default runs `refresh` first and stops with its exit code if it fails; then writes the digest.
- `python -m work_ledger notify [--digest PATH]`: shows a Windows toast for `out/digest/latest.json`: title "Work ledger: weekly digest", body with three counts (at risk recent, going cold, commits on no remote), and clicking opens the Markdown file. Implemented by running `powershell.exe -NoProfile -NonInteractive` with WinRT `Windows.UI.Notifications` (no extra modules), passing values safely (no string interpolation of untrusted text into the script; XML-escape toast text). On a non-Windows platform or failure it prints the summary and exits 1.
- `python -m work_ledger weekly`: `digest` then `notify`. This is what the scheduled task runs.

## Scheduling

`scripts/install-weekly-task.ps1 -Day <DayOfWeek> -Time <HH:mm> [-Python python] [-WhatIf]`:

- Registers a per-user task `WorkLedger\WeeklyDigest` with `Register-ScheduledTask`, weekly trigger, `StartWhenAvailable` (runs after a missed start when the laptop was off), running only when the user is logged on, with no stored password and no elevation.
- Action: the Python executable with `-m work_ledger weekly`, working directory the project root, `PYTHONPATH=src` set through a small wrapper `scripts/weekly.cmd`.
- Idempotent: re-running replaces the task. `scripts/uninstall-weekly-task.ps1` removes it.
- Installing the task changes persistent system configuration, so it runs only after the user's explicit OK.

## Engineering constraints

Python 3.14 stdlib, `unittest`, strict TDD, synthetic fixtures only. Digest computation and Markdown rendering are pure functions. The toast is behind a small port so tests never call PowerShell. Read-only toward repos and `~/.claude`, like every slice.
