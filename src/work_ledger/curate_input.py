"""Model input for weekly curation, selected from the ledger. Pure functions.

Only ledger fields listed in slice 5 reach the model: no paths, keys, session ids, branch
names, prompts or transcript text.
"""

import json
from datetime import timedelta

from .sessions_parse import parse_timestamp

PERIOD_DAYS = 7
MAX_THREADS = 60
MAX_CHARS = 40_000
DOMAIN = "work"
EXCLUDED_STATES = ("discarded",)


def _reference(ledger, now):
    return parse_timestamp(ledger.get("generatedAt")) or now


def _is_recent(thread, since):
    when = parse_timestamp(thread.get("lastAt"))
    return when is not None and when >= since


def _changed(thread, snapshot):
    """True when the thread existed in the snapshot with another effective state."""
    if not snapshot or thread.get("id") not in snapshot:
        return False
    return snapshot[thread["id"]] != thread.get("effectiveState")


def _sort_key(thread):
    when = parse_timestamp(thread.get("lastAt"))
    return (when is None, -(when.timestamp() if when else 0), str(thread.get("id")))


def select_threads(ledger, snapshot, now):
    """Work-domain threads active in the last 7 days or with a changed state, newest first.

    The 7 days count back from the ledger `generatedAt` (`now` when it is unreadable).
    A missing `domain` counts as work: every schemaVersion 2 thread is work.
    """
    since = _reference(ledger, now) - timedelta(days=PERIOD_DAYS)
    picked = [t for t in ledger.get("threads") or []
              if isinstance(t, dict) and t.get("id")
              and (t.get("domain") or DOMAIN) == DOMAIN
              and t.get("effectiveState") not in EXCLUDED_STATES
              and (_is_recent(t, since) or _changed(t, snapshot))]
    return sorted(picked, key=_sort_key)


def _action_counts(actions):
    if not isinstance(actions, dict):
        return {}
    return {name: (entry.get("count") or 0) if isinstance(entry, dict) else 0
            for name, entry in actions.items()}


def thread_facts(thread, project_names):
    """The allowed fields of one thread, as sent to the model."""
    resume = thread.get("resume") or {}
    return {"id": thread.get("id"), "title": thread.get("title"),
            "project": project_names.get(thread.get("projectId")),
            "effectiveState": thread.get("effectiveState"), "firstAt": thread.get("firstAt"),
            "lastAt": thread.get("lastAt"), "sessionCount": thread.get("sessionCount"),
            "gitActions": _action_counts(thread.get("gitActions")),
            "lastRecap": resume.get("lastRecap"), "lastAsk": resume.get("lastAsk")}


def project_names(ledger):
    return {p.get("id"): p.get("name") for p in ledger.get("projects") or []
            if isinstance(p, dict)}


def input_text(data):
    """The exact text written to the model's stdin (and to the dry-run file)."""
    return json.dumps(data, indent=2, ensure_ascii=False)


def build_input(facts, audience, max_pieces, ledger_generated_at, max_threads=MAX_THREADS,
                max_chars=MAX_CHARS):
    """(input dict, threads dropped by the caps). Drops the oldest threads first."""
    kept = list(facts[:max_threads])
    data = {"audience": audience, "maxPieces": max_pieces, "domain": DOMAIN,
            "periodDays": PERIOD_DAYS, "ledgerGeneratedAt": ledger_generated_at,
            "threads": kept}
    while kept and len(input_text(data)) > max_chars:
        kept.pop()
    return data, len(facts) - len(kept)


def previous_snapshot(ledger, latest, rotated):
    """({threadId: effectiveState} of the previous digest, its generatedAt) or (None, None).

    `latest` is `digest/latest.json`. When it was built from this very ledger (the weekly
    job runs digest just before curate), the previous digest is the rotated `previous.json`.
    """
    record = latest
    if latest and latest.get("ledgerGeneratedAt") == ledger.get("generatedAt"):
        record = rotated
    snapshot = (record or {}).get("snapshot")
    if not isinstance(snapshot, dict):
        return None, None
    return dict(snapshot), record.get("generatedAt")
