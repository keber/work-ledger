"""Project-level resume context from the ledger, live git, handoff notes and transcripts. Pure.

Reads go through ports passed in by the caller (`git_reader`, `read_excerpt`,
`handoff_reader`), so this module does no I/O. The CLI prints the result and writes nothing.
"""

import copy
import difflib
import json
from collections import Counter, defaultdict

from .sessions_parse import parse_timestamp
from .threads_state import days_idle

SCHEMA_VERSION = 1
DEFAULT_THREADS = 8
DEFAULT_TRANSCRIPTS = 5
DEFAULT_MAX_CHARS = 30000
MAX_PROJECTS = 6
SESSIONS_PER_THREAD = 2  # most recent sessions excerpted per thread
OVERVIEW_DAYS = 14
PREVIEW = 160
MEANINGFUL_PROMPT = 20  # shorter last prompts ("si", "dale") say nothing on their own
CLOSEST = 5
TRANSCRIPTS_UNAVAILABLE = ("sessions.json could not be read: transcript excerpts unavailable "
                           "(run refresh or pass --refresh)")
PRIVACY_LINE = ("Inferred from the ledger, live git state, handoff notes and session "
                "transcripts. This command writes nothing; run inside a Claude Code session, "
                "this output becomes part of that session's transcript and model context.")
HEADLESS_ENTRYPOINT = "sdk-cli"  # transcripts of `claude -p` runs
REPEATED_PROMPT = 200  # chars compared by the repeated-prompt fallback
REPEATED_MIN = 4  # a prompt shared by this many single-turn sessions marks them automated
TEMPLATE_PREFIX = 40  # chars a templated job's prompts share before the variable part
TEMPLATE_MIN = 2  # job-shaped sessions sharing that prefix
HANDOFF_MIN = 800  # handoff notes are shortened to this before threads are dropped


def _when(value):
    when = parse_timestamp(value)
    return when.timestamp() if when else None


def _by_recent(items):
    return sorted(items, key=lambda x: (_when(x.get("lastAt")) is None,
                                        -(_when(x.get("lastAt")) or 0)))


def _date(value):
    return value[:10] if isinstance(value, str) and value else "?"


def _preview(text, limit=PREVIEW):
    if not isinstance(text, str) or not text.strip():
        return None
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _ledger_info(ledger, now, path):
    generated = ledger.get("generatedAt")
    when = parse_timestamp(generated)
    age = round((now - when).total_seconds() / 3600, 1) if when else None
    return {"path": path, "generatedAt": generated, "ageHours": age}


# ---- matching ----

def match_projects(ledger, query):
    """Projects whose name or path contains the query, or owning a thread whose title does.

    Case-insensitive; most recent activity first.
    """
    q = query.casefold()
    by_title = {t.get("projectId") for t in ledger.get("threads") or []
                if q in str(t.get("title") or "").casefold()}
    found = [p for p in ledger.get("projects") or []
             if q in str(p.get("name") or "").casefold()
             or q in str(p.get("path") or "").casefold() or p.get("id") in by_title]
    return _by_recent(found)


def closest_names(ledger, query, n=CLOSEST):
    names = [p.get("name") for p in ledger.get("projects") or [] if p.get("name")]
    folded = {name.casefold(): name for name in names}
    close = difflib.get_close_matches(query.casefold(), list(folded), n=n, cutoff=0.0)
    return [folded[c] for c in close]


# ---- threads ----

def git_summary(thread):
    if thread.get("gitScope") == "project":
        return "default branch (git state is the project's)"
    git = thread.get("git")
    if not git:
        return "no git"
    parts = [f"branch {git['branch']}" if git.get("branch")
             else f"worktree {git.get('worktreePath') or '?'}"]
    if git.get("risk"):
        parts.append(git["risk"])
    if isinstance(git.get("notOnRemote"), int) and git["notOnRemote"] > 0:
        parts.append(f"{git['notOnRemote']} commits on no remote")
    dirty = git.get("dirty") or {}
    parts += [f"{dirty[k]} {k}" for k in ("staged", "unstaged", "untracked") if dirty.get(k)]
    if git.get("merged"):
        parts.append("merged")
    return ", ".join(parts)


def _quiet_summary(quiet, now):
    if not quiet:
        return None
    idle = [d for d in (days_idle(t.get("lastAt"), now) for t in quiet) if d is not None]
    return {"count": len(quiet),
            "atRisk": sum(1 for t in quiet if t.get("effectiveState") == "at-risk"),
            "minDaysIdle": min(idle) if idle else None,
            "maxDaysIdle": max(idle) if idle else None}


def _meaningful_prompt(text):
    text = " ".join(text.split()) if isinstance(text, str) else ""
    return _preview(text, 300) if len(text) >= MEANINGFUL_PROMPT else None


def thread_view(thread, now):
    resume = thread.get("resume") or {}
    lead = thread.get("lead")
    return {"id": thread.get("id"), "title": thread.get("title"),
            "state": thread.get("effectiveState"), "note": thread.get("note"),
            "firstAt": thread.get("firstAt"), "lastAt": thread.get("lastAt"),
            "daysIdle": days_idle(thread.get("lastAt"), now),
            "sessionCount": thread.get("sessionCount") or 0, "git": git_summary(thread),
            "lastRecap": resume.get("lastRecap"), "lastAsk": resume.get("lastAsk"),
            "lastPrompt": _meaningful_prompt(resume.get("lastPrompt")),
            "resume": f"claude --resume {lead}" if lead else None, "excerpts": []}


def _prompt_key(info):
    """First REPEATED_PROMPT chars of the prompt, whitespace collapsed; None when empty."""
    prompt = info.get("lastPrompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    return " ".join(prompt.split())[:REPEATED_PROMPT]


def _job_shaped(info):
    """One prompt, one reply, no title, not a fork: how unattended runs look.

    Claude Code titles interactive sessions; a forked session repeats its parent's prompt.
    """
    return ((info.get("assistantMessages") or 0) <= 1 and not info.get("titleSource")
            and not info.get("fork"))


def automated_sessions(threads, sessions_index):
    """{session id: signal} for sessions that look like unattended runs.

    Signals, first match wins (prompts compared with whitespace collapsed):

    - `entrypoint`: the transcript says it ran headless (`entrypoint: "sdk-cli"`, what
      `claude -p` records).
    - `prompt-of-automated`: a single-turn session, whatever its entrypoint, whose prompt
      (first REPEATED_PROMPT chars) equals the prompt of a session already found headless,
      in any project. Scheduled jobs can also record `cli` or `claude-desktop` (a `claude
      -p` child inherits the entrypoint of the session that launched it).
    - `repeated-prompt`: a single-turn session whose prompt is shared by REPEATED_MIN or
      more single-turn sessions of the same project.
    - `templated-prompt`: a job-shaped single-turn session (one reply, untitled, not a
      fork) whose first TEMPLATE_PREFIX prompt chars are shared by another job-shaped
      session of the same project: a template with a variable part after the prefix.

    `lastPrompt` stands for the first prompt: for a single-turn session they are the same.
    """
    if not sessions_index:
        return {}
    found, single, headless_prompts = {}, {}, set()
    for t in threads:
        for sid in t.get("sessions") or []:
            info = sessions_index.get(sid) or {}
            prompt = _prompt_key(info)
            if info.get("entrypoint") == HEADLESS_ENTRYPOINT:
                found[sid] = "entrypoint"
                if prompt:
                    headless_prompts.add(prompt)
            elif prompt and (info.get("userMessages") or 0) <= 1:
                single[sid] = (t.get("projectId"), prompt, _job_shaped(info))
    groups, templates = defaultdict(set), defaultdict(set)
    for sid, (project, prompt, shaped) in single.items():
        groups[(project, prompt)].add(sid)
        if shaped and len(prompt) >= TEMPLATE_PREFIX:
            templates[(project, prompt[:TEMPLATE_PREFIX])].add(sid)
    for sid, (project, prompt, shaped) in single.items():
        if prompt in headless_prompts:
            found[sid] = "prompt-of-automated"
        elif len(groups[(project, prompt)]) >= REPEATED_MIN:
            found[sid] = "repeated-prompt"
        elif shaped and len(templates[(project, prompt[:TEMPLATE_PREFIX])]) >= TEMPLATE_MIN:
            found[sid] = "templated-prompt"
    return found


def _is_automated(thread, automated):
    sessions = thread.get("sessions") or []
    return bool(sessions) and all(sid in automated for sid in sessions)


def _automated_summary(threads, automated):
    if not threads:
        return None
    sessions = {sid for t in threads for sid in t.get("sessions") or []}
    return {"threads": len(threads), "sessions": len(sessions),
            "lastAt": _by_recent(threads)[0].get("lastAt"),
            "signals": dict(sorted(Counter(automated[sid] for sid in sessions).items()))}


def _excerpts(thread, sessions_index, read_excerpt, seen):
    """Excerpts of the thread's most recent sessions, oldest first. Unknown sessions skipped.

    `seen` ({entry key: session id}) is shared across the project, so entries a fork copied
    from a session already shown are counted in `sharedWith` instead of printed again.
    """
    found = []
    recent = (thread.get("sessions") or [])[:SESSIONS_PER_THREAD]  # ledger order: newest first
    for sid in reversed(recent):
        info = sessions_index.get(sid) if sessions_index else None
        path = (info or {}).get("transcriptPath")
        if not path:
            continue
        excerpt = dict(read_excerpt(path, seen=seen))
        for key in excerpt.pop("keys", None) or []:
            seen.setdefault(key, sid)
        found.append({"sessionId": sid, "firstAt": info.get("firstAt"),
                      "lastAt": info.get("lastAt"), **excerpt})
    return found


def _latest_activity(project, git):
    dates = [project.get("lastAt")] + [c.get("date") for c in (git or {}).get("recentCommits")
                                         or []][:1]
    dated = [d for d in dates if _when(d) is not None]
    return max(dated, key=_when) if dated else None


def _handoff(notes, latest):
    """Notes with `olderThanActivity`: modified before the latest session or commit."""
    out = []
    for n in notes or []:
        modified, last = _when(n.get("modifiedAt")), _when(latest)
        out.append({**n, "olderThanActivity": bool(modified and last and modified < last),
                    "lastActivityAt": latest})
    return out


def _project_view(project, threads, now, ports, automated, top_n, top_k):
    owned = [t for t in threads if t.get("projectId") == project.get("id")]
    robots = [t for t in owned if t.get("sessionCount") and _is_automated(t, automated)]
    active = _by_recent([t for t in owned if t.get("sessionCount") and t not in robots])
    quiet = [t for t in owned if not t.get("sessionCount")]
    git = ports["git"](project.get("path"))
    views, seen = [], {}
    for index, t in enumerate(active[:top_n]):
        view = thread_view(t, now)
        if index < top_k:
            view["excerpts"] = _excerpts(t, ports["sessions"], ports["excerpt"], seen)
        views.append(view)
    return {"id": project.get("id"), "name": project.get("name"), "path": project.get("path"),
            "kind": project.get("kind"), "atRisk": bool(project.get("atRisk")),
            "lastAt": project.get("lastAt"), "daysIdle": days_idle(project.get("lastAt"), now),
            "threadCount": len(owned), "sessionCount": sum(t.get("sessionCount") or 0 for t in owned),
            "git": git,
            "handoff": _handoff(ports["handoff"](project.get("path")),
                                _latest_activity(project, git)),
            "quietThreads": _quiet_summary(quiet, now),
            "automatedRuns": _automated_summary(robots, automated),
            "threads": views, "moreThreads": max(0, len(active) - top_n)}


def _no_handoff(path):
    return []


def build_query_context(ledger, query, now, git_reader, sessions_index, read_excerpt,
                        handoff_reader=_no_handoff, threads=DEFAULT_THREADS,
                        transcripts=DEFAULT_TRANSCRIPTS, ledger_path=None):
    """Context for the projects matching `query` (at most MAX_PROJECTS get detail).

    `sessions_index` is {session id: {transcriptPath, firstAt, lastAt, entrypoint,
    userMessages, lastPrompt}} or None when the sessions report could not be read.
    `read_excerpt(path, seen=...)` and `handoff_reader(project path)` are the read ports.
    """
    matched = match_projects(ledger, query)
    all_threads = ledger.get("threads") or []
    notes = [] if sessions_index is not None else [TRANSCRIPTS_UNAVAILABLE]
    ports = {"git": git_reader, "sessions": sessions_index, "excerpt": read_excerpt,
             "handoff": handoff_reader}
    automated = automated_sessions(all_threads, sessions_index)
    return {"schemaVersion": SCHEMA_VERSION, "mode": "query", "query": query,
            "ledger": _ledger_info(ledger, now, ledger_path),
            "projects": [_project_view(p, all_threads, now, ports, automated, threads,
                                       transcripts)
                         for p in matched[:MAX_PROJECTS]],
            "alsoMatched": [p.get("name") for p in matched[MAX_PROJECTS:]],
            "suggestions": [] if matched else closest_names(ledger, query),
            "notes": notes, "truncation": None}


# ---- overview ----

def _latest_thread(project, threads, automated):
    owned = _by_recent([t for t in threads
                        if t.get("projectId") == project.get("id") and t.get("sessionCount")
                        and not _is_automated(t, automated)])
    if not owned:
        return None
    latest = owned[0]
    resume = latest.get("resume") or {}
    return {"title": latest.get("title"), "state": latest.get("effectiveState"),
            "lastRecap": _preview(resume.get("lastRecap"))}


def build_overview(ledger, now, ledger_path=None, sessions_index=None):
    """Projects active in the last OVERVIEW_DAYS days or at risk, most recent first."""
    threads = ledger.get("threads") or []
    automated = automated_sessions(threads, sessions_index)
    rows = []
    for p in _by_recent(ledger.get("projects") or []):
        idle = days_idle(p.get("lastAt"), now)
        if not (p.get("atRisk") or (idle is not None and idle <= OVERVIEW_DAYS)):
            continue
        rows.append({"id": p.get("id"), "name": p.get("name"), "path": p.get("path"),
                     "lastAt": p.get("lastAt"), "daysIdle": idle,
                     "atRisk": bool(p.get("atRisk")),
                     "latestThread": _latest_thread(p, threads, automated)})
    return {"schemaVersion": SCHEMA_VERSION, "mode": "overview", "query": None,
            "ledger": _ledger_info(ledger, now, ledger_path), "projects": rows,
            "alsoMatched": [], "suggestions": [], "notes": [], "truncation": None}


# ---- size cap ----

def _drop_one(ctx, dropped):
    """Drop the least important remaining piece.

    Order: a transcript excerpt, then shorten a handoff note to HANDOFF_MIN chars, then a
    thread, then a whole project (the first one is kept).
    """
    projects = ctx["projects"]
    for p in reversed(projects):
        for t in reversed(p.get("threads") or []):
            if t.get("excerpts"):
                t["excerpts"].pop()
                dropped["droppedExcerpts"] += 1
                return True
    for p in reversed(projects):
        for n in reversed(p.get("handoff") or []):
            if len(n.get("text") or "") > HANDOFF_MIN:
                n["text"] = n["text"][:HANDOFF_MIN]
                n["truncated"] = True
                n["shortened"] = True
                dropped["shortenedHandoffNotes"] += 1
                return True
    for p in reversed(projects):
        if p.get("threads"):
            p["threads"].pop()
            p["moreThreads"] = p.get("moreThreads", 0) + 1
            dropped["droppedThreads"] += 1
            return True
    if len(projects) > 1:
        projects.pop()
        dropped["droppedProjects"] += 1
        return True
    return False


def truncation_note(trunc):
    note = (f"Output truncated to fit --max-chars {trunc['maxChars']}: dropped "
            f"{trunc['droppedExcerpts']} transcript excerpts, shortened "
            f"{trunc['shortenedHandoffNotes']} handoff notes, dropped "
            f"{trunc['droppedThreads']} threads and {trunc['droppedProjects']} projects")
    if trunc.get("hardCut"):
        note += ", then cut the text"
    return note + ". Narrow the query or raise --max-chars."


def fit(ctx, max_chars, render):
    """(text, context) with the rendered text within max_chars where possible.

    Pieces are dropped least important first. Markdown is cut as a last resort; JSON is
    never cut (it would not parse), so `overLimit` marks a JSON still above the cap.
    """
    ctx = copy.deepcopy(ctx)
    text = render(ctx)
    if len(text) <= max_chars:
        return text, ctx
    trunc = {"maxChars": max_chars, "droppedExcerpts": 0, "shortenedHandoffNotes": 0,
             "droppedThreads": 0, "droppedProjects": 0, "hardCut": False, "overLimit": False}
    ctx["truncation"] = trunc
    text = render(ctx)
    while len(text) > max_chars and _drop_one(ctx, trunc):
        text = render(ctx)
    if len(text) <= max_chars:
        return text, ctx
    if render is render_json:
        trunc["overLimit"] = True
        return render(ctx), ctx
    trunc["hardCut"] = True
    tail = "\n\n> " + truncation_note(trunc) + "\n"
    return text[:max(0, max_chars - len(tail))] + tail, ctx


# ---- rendering ----

def render_json(ctx):
    return json.dumps(ctx, ensure_ascii=False, indent=2)


def _age(hours):
    if hours is None:
        return "age unknown"
    return f"{hours:.0f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"


def _idle(days):
    return "idle ?" if days is None else f"{days}d idle"


def _header(ctx):
    led = ctx["ledger"]
    title = (f'# Work context: "{ctx["query"]}"' if ctx["mode"] == "query"
             else "# Work context: overview")
    lines = [title, "",
             f"Ledger generated {led.get('generatedAt') or '?'} ({_age(led.get('ageHours'))})"
             + (f": {led['path']}" if led.get("path") else ""),
             PRIVACY_LINE]
    lines += [f"Note: {n}" for n in ctx.get("notes") or []]
    return lines


def _dirty_text(dirty):
    if not dirty:
        return "clean"
    parts = [f"{dirty[k]} {k}" for k in ("staged", "unstaged", "untracked") if dirty.get(k)]
    return ", ".join(parts) or "clean"


def _git_lines(git):
    status = (git or {}).get("status")
    if status == "missing":
        return ["- path not found on this machine"]
    if status == "not-a-repo":
        return ["- not a git repo"]
    if status != "ok":
        return [f"- git failed: {(git or {}).get('error') or 'unknown error'}"]
    lines = [f"- Branch: {git.get('branch') or '(detached)'} "
             f"(default {git.get('defaultBranch') or '?'}) | working tree: "
             f"{_dirty_text(git.get('dirty'))}",
             f"- Commits on no remote: {git.get('notOnRemote')} in local branches "
             f"({git.get('headNotOnRemote')} on the current one)"]
    if git.get("recentCommits"):
        lines.append("- Recent commits on the current branch:")
        lines += [f"  - {_date(c.get('date'))} {c.get('subject')}" for c in git["recentCommits"]]
    branches = git.get("unmergedBranches") or []
    if branches:
        lines.append(f"- Branches with commits not in {git.get('defaultBranch')}:")
        for b in branches:
            commit = b.get("lastCommit") or {}
            mark = " [current]" if b.get("current") else ""
            lines.append(f"  - {b['name']} ({b['ahead']} ahead, {_date(commit.get('date'))}: "
                         f"{commit.get('subject')}){mark}")
        if git.get("moreUnmergedBranches"):
            lines.append(f"  - ... {git['moreUnmergedBranches']} more")
    return lines


def _excerpt_lines(ex):
    lines = [f"  - Session {ex['sessionId']} ({_date(ex.get('firstAt'))} -> "
             f"{_date(ex.get('lastAt'))}):"]
    if ex.get("error"):
        return lines + [f"    - {ex['error']}"]
    for sid, count in sorted((ex.get("sharedWith") or {}).items()):
        lines.append(f"    - ... {count} shared entries with session {sid} omitted ...")
    for i, entry in enumerate(ex.get("entries") or []):
        if ex.get("gapAfter") is not None and i == ex["gapAfter"]:
            lines.append(f"    - ... {ex['omitted']} entries omitted ...")
        lines.append(f"    - [{(entry.get('at') or '?')[:16]}] {entry['role']}: {entry['text']}")
    if not ex.get("entries") and not ex.get("sharedWith"):
        lines.append("    - (no prompts or replies)")
    return lines


def _thread_lines(index, t):
    lines = [f"{index}. **{t['title']}** | {t['state']} | {_date(t['firstAt'])} -> "
             f"{_date(t['lastAt'])} | {_idle(t['daysIdle'])} | {t['sessionCount']} sessions",
             f"   - git: {t['git']}"]
    for label, key in (("note", "note"), ("recap", "lastRecap"), ("ask", "lastAsk"),
                       ("last prompt", "lastPrompt")):
        if t.get(key):
            lines.append(f"   - {label}: {t[key]}")
    if t.get("resume"):
        lines.append(f"   - resume: `{t['resume']}`")
    if t.get("excerpts"):
        lines.append("   - transcript excerpts (oldest session first):")
        for ex in t["excerpts"]:
            lines += ["    " + line for line in _excerpt_lines(ex)]
    return lines


def _quiet_line(q):
    if not q:
        return None
    rng = (f"{q['minDaysIdle']}-{q['maxDaysIdle']}d" if q.get("minDaysIdle") is not None
           else "?")
    risk = f" ({q['atRisk']} at risk)" if q.get("atRisk") else ""
    return (f"- {q['count']} threads without sessions{risk}, idle {rng} "
            "(agent worktrees or branches only; collapsed)")


def _automated_line(a):
    if not a:
        return None
    signals = ", ".join(f"{name} {count}" for name, count in a["signals"].items())
    return (f"- {a['sessions']} automated runs ({signals}), last on "
            f"{_date(a.get('lastAt'))}, in {a['threads']} threads (excluded from the ranking)")


FENCE = "~~~~"


def _handoff_lines(notes):
    if not notes:
        return []
    lines = ["", "### Handoff notes (hand-written in the repo, most recent first)", ""]
    for n in notes:
        stale = (f" | older than the last activity ({_date(n.get('lastActivityAt'))}): "
                 "possibly stale" if n.get("olderThanActivity") else "")
        lines += [f"- {n['path']} (modified {(n.get('modifiedAt') or '?')[:16]}){stale}",
                  "", FENCE + "text", (n.get("text") or "").replace(FENCE, "~~~"), FENCE]
        if n.get("truncated"):
            lines.append(_note_cut(n))
        lines.append("")
    return lines


TOC_MAX = 80  # headings listed for a truncated note


def _note_cut(n):
    """Where the rest of a truncated note is: size, full path and its headings by line."""
    shown = (f"first {HANDOFF_MIN} chars shown, shortened by --max-chars" if n.get("shortened")
             else "title and lead shown")
    lines = [f"[note truncated: {n.get('bytes')} bytes, {n.get('lines')} lines; {shown}. "
             f"Read the full file: {n['path']}]"]
    toc = n.get("toc") or []
    if toc:
        lines += ["", "Contents (line: heading):"]
        lines += [f"{'  ' * (max(1, h.get('level') or 1) - 1)}- L{h.get('line')} "
                  f"{'#' * (h.get('level') or 1)} {h.get('heading')}" for h in toc[:TOC_MAX]]
        if len(toc) > TOC_MAX:
            lines.append(f"- ... {len(toc) - TOC_MAX} more headings in the file")
    return "\n".join(lines)


def _project_lines(p):
    risk = " | AT RISK" if p.get("atRisk") else ""
    lines = ["", f"## {p['name']}", "",
             f"Path: {p.get('path') or '?'} | last activity {_date(p.get('lastAt'))} "
             f"({_idle(p.get('daysIdle'))}) | {p['threadCount']} threads, "
             f"{p['sessionCount']} sessions{risk}",
             "", "### Git (live, read-only, remotes as of the last fetch)", ""]
    lines += _git_lines(p.get("git"))
    lines += _handoff_lines(p.get("handoff"))
    shown = len(p.get("threads") or [])
    lines += ["", f"### Threads ({shown} shown, most recent first)", ""]
    quiet = _quiet_line(p.get("quietThreads"))
    if quiet:
        lines.append(quiet)
    robots = _automated_line(p.get("automatedRuns"))
    if robots:
        lines.append(robots)
    for i, t in enumerate(p.get("threads") or [], 1):
        lines += _thread_lines(i, t)
    if p.get("moreThreads"):
        lines.append(f"- ... {p['moreThreads']} older threads not shown (--threads N)")
    if not shown and not quiet and not robots:
        lines.append("- no threads")
    return lines


def _overview_line(p):
    risk = " | AT RISK" if p.get("atRisk") else ""
    line = f"- **{p['name']}** | {_idle(p.get('daysIdle'))}{risk}"
    latest = p.get("latestThread")
    if latest:
        line += f" | latest: {latest['title']} ({latest['state']})"
        if latest.get("lastRecap"):
            line += f" | recap: {latest['lastRecap']}"
    return line


def render_markdown(ctx):
    lines = _header(ctx)
    if ctx["mode"] == "overview":
        lines += ["", f"## Active in the last {OVERVIEW_DAYS} days or at risk", ""]
        lines += [_overview_line(p) for p in ctx["projects"]] or ["- nothing recent"]
        lines += ["", 'Detail: `python -m work_ledger context "<name>"`']
    else:
        for p in ctx["projects"]:
            lines += _project_lines(p)
        if ctx.get("alsoMatched"):
            lines += ["", f"Also matched (not detailed): {', '.join(ctx['alsoMatched'])}. "
                          "Use a narrower query."]
        if not ctx["projects"]:
            closest = ", ".join(ctx.get("suggestions") or []) or "none"
            lines += ["", f'No project matches "{ctx["query"]}". Closest: {closest}']
    if ctx.get("truncation"):
        lines += ["", "> " + truncation_note(ctx["truncation"])]
    return "\n".join(lines) + "\n"
