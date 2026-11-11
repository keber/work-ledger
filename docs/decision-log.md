# Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-11-03 | Three layers: ledger, views, background jobs | Views and jobs are cheap once a reliable ledger exists |
| 2026-11-03 | MVP sources: Claude Code and Codex local JSONL, git, Engram | They cover most of the work and are readable locally; cloud chats need manual export |
| 2026-11-03 | Single instance on the work laptop | The personal machine is rarely used; no sync design |
| 2026-11-03 | Two domains (work, personal/academic) tagged at ingestion, never mixed in curation | Prevents internal data leaking into personal publications |
| 2026-11-03 | Publication requires sanitization and human approval; first target is a wiki or local folder | Data governance |
| 2026-11-03 | View: pane inside the Claude desktop app (mod), keeping a Windows tray app possible | Attention is already in the Claude app; the tray app stays open as another adapter |
| 2026-11-03 | Logic lives in a UI-less scanner CLI writing `ledger.json`; scheduled jobs run outside the mod | Mods cannot read other sessions and their timers die with the session |
| 2026-11-04 | First slice: read-only git inventory of repos, worktrees and branches | Unblocks the pending worktree cleanup from the SWOT session; deterministic and useful alone |
| 2026-11-04 | Python 3.14, standard library only, unittest with real temp repos | No dependencies to install or govern |
| 2026-11-04 | Loss risk measured by commits on no remote (`notOnRemote`), not `ahead` | `ahead` overstated loss (58 vs 1 on one branch) |
| 2026-11-06 | Pending-work reminder is weekly (not every 15 days), Thursdays 15:00, via a per-user Windows scheduled task with StartWhenAvailable | User preference; mod timers die with the session |
| 2026-11-05 | Two levels: project (repo or directory) groups threads; on the default branch a thread is a fork family or a single session, and git state belongs to the project | Trunk-based QA repos put 79 sessions into one repo + branch thread |
| 2026-11-03 | Work thread = repo + branch, or folder + title + sidebar group; write anchor overrides cwd; cross-repo cohesion via related links | User confirmed the default; cross-repo threads exist but are not the general case |
