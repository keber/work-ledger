# Slice 0: git inventory of repos, worktrees and branches

## Goal

Answer, for every local repo, worktree and branch: is there work that would be lost if it were deleted? This unblocks the pending worktree cleanup (QW3 of the 2026-10-27 SWOT session) and becomes the git half of the ledger.

## Scope

- **Read-only.** The tool never deletes, prunes, checks out, fetches or writes inside a repo. It only runs read-only git commands.
- **No network by default.** Remote-tracking refs may be stale; the report states when each repo's remote refs were last updated (mtime of `FETCH_HEAD` when present). `--fetch` is out of scope for this slice.
- Discovery from configurable roots. Defaults: `~/Proyectos` and `~/source/repos`, max depth 2. A directory is a repo when it contains `.git` (dir or file).
- Repos are deduplicated by git common dir: a worktree folder found by discovery is reported under its main repo, not twice.

## Facts collected

Per repo (main working tree):
- path, common dir, default branch (`origin/HEAD` target; fallback `main`, then `master`; `null` if none), remotes present (yes/no), last fetch time.

Per worktree (`git worktree list --porcelain`):
- path, branch (or detached HEAD sha), exists on disk, locked, prunable;
- dirty: counts of staged, unstaged and untracked entries (`git status --porcelain=v1`);
- upstream, ahead/behind upstream;
- merged into default branch (`git merge-base --is-ancestor`);
- last commit date and subject.

Per local branch not checked out in any worktree:
- upstream, ahead/behind, merged into default branch, last commit date and subject.

## Classification

Each worktree and branch gets exactly one `risk`, first match wins:

| risk | Condition |
|---|---|
| `missing` | Worktree registered but its folder does not exist |
| `uncommitted` | Dirty (any staged, unstaged or untracked entry) |
| `unpushed` | Commits not on any remote: no upstream and not merged, or ahead of upstream |
| `unmerged` | Pushed but not merged into the default branch |
| `safe` | Clean, nothing unpushed, merged into the default branch |
| `unknown` | Cannot be determined (no default branch, git error) |

The main working tree of a repo is never classified `safe` for removal; it gets `risk` for its state but is flagged `isMain: true`.

## Output

- `out/git-inventory.json`: machine-readable, versioned (`schemaVersion: 2` since the 2026-11-04 refinements), with `generatedAt` and every fact above.
- `out/git-inventory.md`: human report, grouped by repo, worst risk first, with a summary table of counts per risk.
- Exit code 0 on success even if some repos fail; failures appear as `unknown` with the error message. Non-zero only on invalid arguments or unwritable output.

## Engineering constraints

- Python 3.14, standard library only. Tests with `unittest`, building real temporary git repos (no git mocks for behavior tests).
- Git invoked as `git -C <path> ...` with argv lists (no shell), a timeout per call, and inherited `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_COMMON_DIR`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_NAMESPACE`, `GIT_CEILING_DIRECTORIES` removed from the environment.
- Collection (git facts) and classification (pure function) are separate modules so classification is unit-tested without git.
- Paths in output use forward slashes and are absolute.

## Implementation decisions (2026-11-04)

- A clean, pushed, merged main worktree gets a seventh risk value, `main`, instead of `safe`.
- Severity order for reports: uncommitted > unpushed > unknown > missing > unmerged > main > safe.
- Read-only enforcement: `--no-optional-locks` and `GIT_OPTIONAL_LOCKS=0` on every call; `GIT_TERMINAL_PROMPT=0`; 30 s timeout per call.

## First real run (2026-11-04)

62 repos under the default roots, 107 s, 66 tests passing. Item counts: uncommitted 36, unpushed 12, unknown 3, unmerged 23, main 21, safe 65.

### Classification noise found

1. **Untracked-only dirt inflates `uncommitted`.** Many main worktrees are dirty only because of tool folders (`.atl/`, `.tmp/`) or new reference folders. Losing untracked files matters, but it is a different risk from modified tracked files.
2. **`unmerged` mixes loss risk with normal workflow.** Long-lived team branches (`qa-test`, `development`, other people's sprint branches) are pushed and not merged by design. Nothing is lost if the local copy is deleted.
3. **`ahead` is empty when there is no upstream.** The useful number is commits not on any remote: `git rev-list --count <branch> --not --remotes`.
4. **Remote refs are often stale.** Several repos were never fetched; their `unpushed`/`unmerged` state is relative to old remote refs.

### Refinements (approved 2026-11-04, schemaVersion 2)

1. **Split `uncommitted`**: `modified` (any staged or unstaged tracked change) and `untracked` (only untracked entries, after the ignore list).
2. **`notOnRemote`**: number of commits reachable from the branch and not from any remote ref (`git rev-list --count <ref> --not --remotes`). `unpushed` means `notOnRemote > 0`. In a repo with no remotes every commit counts. `ahead`/`behind` stay as facts.
3. **`pushed`**: replaces `unmerged`. Clean, nothing unpushed, not merged into the default branch. Informational: deleting the local copy loses nothing.
4. **Untracked ignore list**: untracked entries whose path starts with an ignored prefix are not counted in `dirty.untracked`; they are counted in `dirty.ignoredUntracked`. Defaults `.atl/`, `.tmp/`; extend with repeatable `--ignore-untracked PREFIX`.
5. **Ownership**: `lastCommit.isOwn` is true when the last commit's author email equals the repo's effective `user.email` (case-insensitive); `null` when `user.email` is unset. Other people's emails are not stored. The Markdown report tags non-own items as `others`.

New first-match risk table:

| risk | Condition |
|---|---|
| `missing` | Worktree registered but its folder does not exist |
| `modified` | Staged or unstaged tracked changes |
| `unpushed` | `notOnRemote > 0` |
| `untracked` | Only untracked entries (after ignore list) |
| `unknown` | Cannot be determined |
| `pushed` | Clean, nothing unpushed, not merged into default |
| `safe` | Clean, nothing unpushed, merged into default |

A main worktree that would be `safe` or `pushed` gets `main`. `unknown` applies when the default branch is missing only if merge state is needed (clean and nothing unpushed); `notOnRemote` does not need the default branch.

Severity order for reports: modified > unpushed > untracked > unknown > missing > pushed > main > safe.

## Second real run (2026-11-04, schemaVersion 2)

62 repos, 94 tests passing. Item counts: modified 24, unpushed 8, untracked 8, unknown 3, pushed 12, main 39, safe 66 (v1: uncommitted 36, unpushed 12, unmerged 23).

### What the refinements changed

- **`ahead` overstated loss.** Branch A (repo QA B) was 58 commits ahead of its upstream, but only 1 commit is not on any remote. `notOnRemote` is the right measure of loss.
- **Local-only repos surface.** Tool repo A (19 commits) and tool repo B (3) have commits on no remote at all: the whole project has no backup.
- **Team branches left the risk list.** Pushed-but-unmerged branches are now `pushed` (12), not a loss risk.

### Remaining limits

- `isOwn` looks only at the last commit. A worktree whose last commit is someone else's can still hold the user's own uncommitted changes, so `[others]` on a `modified` worktree is not a reason to ignore it.
- `unknown` remains for 2 repos without any commit and 1 repo whose state needs a closer look (tool repo C).
- Remote refs are as fresh as the last fetch; the scan never fetches.
