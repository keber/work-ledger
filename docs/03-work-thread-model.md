# Work thread model

A **work thread** is the unit of the ledger: one piece of work with a goal, possibly spread across several sessions and forks.

## Default identity

- **With a repo**: thread = repo + branch. Worktrees and forks of the same branch belong to the same thread; worktree paths resolve to their main repo.
- **Without a repo**: thread = folder + session title + sidebar group. The user can merge or split threads manually.

## The cross-repo case

A thread can start in a repo unrelated to it. Examples given by the user: the LaTeX and PDF skills, the accent-mark work, the user story and task monitor. These were born inside some project session but their real subject lives elsewhere.

This is not the general case, but the model must not break on it.

### Anchor by what was written, not where the session ran

The session's cwd says where Claude was started; the paths it wrote say what the work was about. Transcripts record every `Write` / `Edit` / `NotebookEdit` tool call with its `file_path`, so the scanner can compute a **write anchor**:

- If most writes fall inside the cwd repo, the anchor is that repo + branch (default case).
- If most writes fall outside it (for example under `~/.claude/skills/latex-pdf/`), the anchor is the root of those writes. The session joins the thread of that anchor, not of its cwd.
- A session that wrote nothing keeps its cwd anchor and is flagged as exploratory.

### Identity resolution order

1. **Manual override** (`overrides.json`): always wins.
2. **Write anchor**: when it differs from cwd.
3. **cwd repo + branch**.
4. **No repo**: folder + title + sidebar group.

## Related threads (links, not merges)

Evidence of cohesion can be scattered across repos, sessions and folders. Instead of forcing it into one thread, the ledger keeps **related** edges between threads, suggested from shared evidence:

- shared write paths;
- shared work item IDs of the issue tracker (system A) mentioned in the transcripts;
- shared distinctive keywords in titles or summaries.

Suggestions are shown for confirmation; only confirmed links are used by views and curators.

## Most advanced session in a thread

When several sessions or forks belong to one thread, the **lead session** is chosen by:

1. Git evidence: the branch with commits merged, or the most commits ahead of its base.
2. Without git evidence: the most recent session with a closure signal (summary, wrap-up, explicit "done").
3. Otherwise: the most recent activity.

## Thread state

| State | Set by |
|---|---|
| `active`, `paused`, `discarded`, `done` | User mark (one click), stored in `overrides.json` |
| Suggested state | Scanner: git state for repo threads; transcript signals (closure, surviving output files, days since last message) for non-repo threads |

The user mark always wins over the suggestion. Git facts (uncommitted, unpushed, unmerged) are shown even on threads marked `done`, as warnings.
