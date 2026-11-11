"""One curation call per audience: prompt, port call, validation and candidate selection.

Everything here is pure except `load_prompt` (reads a package file) and the injected port.
"""

from importlib import resources

from .curate_claude import ClaudeError
from .curate_input import input_text
from .curate_schema import SchemaError, schema_json, validate_output

AUDIENCES = {
    "portfolio": {"visibility": "internal", "max": 2},
    "team": {"visibility": "internal", "max": 2},
    "public": {"visibility": "external", "max": 1},
}
CHECKED_FIELDS = ("title", "summary", "body", "rationale")


def is_external(audience):
    return AUDIENCES[audience]["visibility"] == "external"


def load_prompt(audience):
    """System prompt text from `work_ledger/prompts/<audience>.md`."""
    if audience not in AUDIENCES:
        raise ValueError(f"unknown audience: {audience}")
    return resources.files("work_ledger").joinpath("prompts", f"{audience}.md") \
        .read_text(encoding="utf-8")


def _rejected(index, reason, rules=()):
    return {"candidate": index + 1, "reason": reason, "rules": list(rules)}


def select_candidates(pieces, input_ids, maximum, check=None):
    """(kept, rejected). `check(texts) -> [rule]` runs for external audiences.

    Candidates citing a thread not in the input are discarded, then failing the check,
    then the top `maximum` by relevance are kept (ties keep the model's order).
    Rejections carry the 1-based candidate number and rule names, never the text.
    """
    rejected, eligible = [], []
    for i, piece in enumerate(pieces):
        if any(tid not in input_ids for tid in piece["sourceThreadIds"]):
            rejected.append(_rejected(i, "unknown-source-thread"))
            continue
        if check is not None:
            rules = check([piece[f] for f in CHECKED_FIELDS])
            if rules:
                rejected.append(_rejected(i, "sanitization", rules))
                continue
        eligible.append((i, piece))
    ranked = sorted(eligible, key=lambda item: (-item[1]["relevance"], item[0]))
    kept = [p for _, p in ranked[:maximum]]
    rejected += [_rejected(i, "over-limit") for i, _ in ranked[maximum:]]
    rejected.sort(key=lambda r: r["candidate"])
    return kept, rejected


def _failed(warning, warnings=()):
    return {"status": "failed", "warnings": [*warnings, warning], "candidates": 0, "kept": [],
            "rejected": []}


def run_audience(audience, data, port, system_prompt, check=None):
    """Result dict for one audience. A failed call becomes `status: failed` with a warning."""
    external = is_external(audience)
    if external and check is None:
        raise ValueError(f"{audience} is external: a sanitization check is required")
    try:
        reply = port(system_prompt, schema_json(), input_text(data))
    except ClaudeError as exc:
        return _failed(f"claude: {exc}")
    warnings = list(reply.warnings)
    try:
        pieces = validate_output(reply.output)
    except SchemaError as exc:
        return _failed(f"schema mismatch: {exc}", warnings)
    input_ids = {t.get("id") for t in data.get("threads") or []}
    kept, rejected = select_candidates(pieces, input_ids, AUDIENCES[audience]["max"],
                                       check if external else None)
    return {"status": "ok", "warnings": warnings, "candidates": len(pieces), "kept": kept,
            "rejected": rejected}
