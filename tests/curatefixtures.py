"""Synthetic ledger threads and model outputs for weekly curation."""

from datetime import datetime, timezone

from tests.digestfixtures import ledger, project, thread as digest_thread

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
LEDGER_AT = "2026-11-12T08:55:00+00:00"


def actions(commit=0, push=0, merge=0, pr=0):
    return {"commit": {"count": commit, "lastAt": None}, "push": {"count": push, "lastAt": None},
            "merge": {"count": merge, "lastAt": None},
            "pr-create": {"count": pr, "lastAt": None}}


def thread(tid, state="open", last_at="2026-11-10T10:00:00+00:00", project="p-app", title=None,
           recap=None, ask=None, sessions=1, domain="work", commits=0, git=None):
    """Thread with the fields curation reads plus fields it must never send."""
    item = digest_thread(tid, state, project=project, title=title, lead=f"s-{tid}",
                         recap=recap, ask=ask, git=git)
    item.update({"firstAt": "2026-11-01T10:00:00+00:00", "lastAt": last_at,
                 "sessionCount": sessions, "domain": domain, "gitActions": actions(commit=commits),
                 "note": "private note"})
    item["resume"]["lastPrompt"] = "secret prompt text"
    return item


def curate_ledger(threads, projects=None, generated_at=LEDGER_AT):
    projects = [project("p-app", "app")] if projects is None else projects
    return ledger(threads, projects, generated_at=generated_at)


def piece(title="Avance semanal", summary="Resumen corto.", body="Cuerpo del texto.",
          sources=("a",), relevance=0.5, rationale="Relevante para el equipo."):
    return {"title": title, "summary": summary, "body": body, "sourceThreadIds": list(sources),
            "relevance": relevance, "rationale": rationale}


def output(*pieces):
    return {"pieces": list(pieces)}
