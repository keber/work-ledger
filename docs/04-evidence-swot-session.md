# Evidence: SWOT session of 2026-10-27

Source: Claude Code session S1 (a SWOT and improvement-plan session; CLI session id withheld, cwd `ClaudeSession`), summarized 2026-11-03. The SWOT and plan were only produced in chat; no report file exists.

## Findings relevant to this tool

- **Duplicate sidebar headers**: the desktop sidebar mixes user groups with automatic headers derived from each session's cwd. Worktrees add extra "ghost" headers. Those headers cannot be dragged into groups.
- **Low grouping**: about 50 sessions without group vs 7 grouped (before cleanup).
- **Weak titles**: repeated or generic titles (the generic project-review title of session S2 ×3, a bare ticket id `DEF-XXX` ×4, several generic "let's continue" titles like session S3's).
- **Catch-all folder**: `ClaudeSession` is not a git repo and has no `CLAUDE.md`; it holds 61 transcripts (about 450 MB) of unrelated work.
- **Worktree sprawl**: 17 worktrees under `.claude\worktrees` plus 7 top-level `*-wt-*` folders; branch state never inventoried.
- **Rework and forgotten work**: 4 sessions on the same defect; unmerged branches such as branch B.

## Plan status

| Quick win | Status |
|---|---|
| QW1 Reorganize sidebar (groups, 42 August sessions archived) | Done |
| QW2 Title convention "Project · Type · Topic" | Pending |
| QW3 Worktree cleanup, gated on per-worktree branch status | Pending; no worktree inspected |

## Implications for the design

1. **QW3 is the ledger's first natural use case.** Inventorying each worktree's branch state (uncommitted, unpushed, unmerged) is deterministic, valuable alone, and is exactly what was missing to clean up safely.
2. **Titles are a weak grouping signal.** Generic and repeated titles mean the write anchor and git evidence must weigh more than title similarity.
3. **Non-repo work is concentrated in one catch-all folder.** Folder-based grouping says little there; write anchor, title and sidebar group carry the grouping.
4. **Volume requires an incremental scanner.** About 667 MB of transcripts across 21 project folders: parse only new or changed files (mtime and offset cache).
5. **IDs differ between the app and the CLI.** The desktop app's session id (`local_…`) is not present in the CLI transcript; a mapping is needed to link a thread to its app session.
6. **Custom titles are stored locally** in `<transcript-id>/custom-title.json` (36 found on 2026-11-03). Sessions without a custom title need another source.
