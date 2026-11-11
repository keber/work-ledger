"""Proposal files, the inbox index, and approval or discard of pieces.

Layout: `<out>/pieces/inbox/<YYYY-MM-DD>/<audience>-<n>.md` plus `index.json`. Paths are
built only from validated parts (date, audience id, number) and derived slugs; model text
never reaches a path.

Front matter: one `key: value` per line between `---` lines, each value JSON-encoded (so
also valid YAML). Values a user edits by hand without quotes are read as plain strings.
"""

import json
import os
import re
import unicodedata
from datetime import date as date_type
from datetime import datetime, timezone

from .curate_build import AUDIENCES, is_external
from .discover import to_posix

INDEX_VERSION = 1
INDEX_NAME = "index.json"
INBOX_PARTS = ("pieces", "inbox")
STATUSES = ("proposed", "approved", "discarded")
FRONT_MATTER_KEYS = ("id", "audience", "visibility", "status", "title", "summary",
                     "sourceThreadIds", "relevance", "rationale", "generatedAt", "model")
SLUG_MAX = 60
_ID = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z]+)-([1-9]\d{0,3})$")
_FILE = re.compile(r"^([a-z]+)-([1-9]\d{0,3})\.md$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FENCE = "---"


class PieceError(Exception):
    """A piece or the inbox index is missing, invalid, or in the wrong status."""


def inbox_dir(out_dir, date):
    return os.path.join(out_dir, *INBOX_PARTS, date)


def _valid_date(text):
    if not _DATE.match(text):
        return False
    try:
        date_type.fromisoformat(text)
    except ValueError:
        return False
    return True


def parse_piece_id(piece_id):
    """(date, audience, n) of `<YYYY-MM-DD>-<audience>-<n>`. Raises PieceError."""
    match = _ID.match(piece_id or "")
    if not match or not _valid_date(match.group(1)) or match.group(2) not in AUDIENCES:
        raise PieceError(f"invalid piece id: {piece_id!r} (expected YYYY-MM-DD-<audience>-<n>)")
    return match.group(1), match.group(2), int(match.group(3))


def slugify(title, fallback):
    """ASCII `[a-z0-9-]` slug of a title, at most SLUG_MAX characters; `fallback` if empty."""
    decomposed = unicodedata.normalize("NFKD", str(title or ""))
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = slug[:SLUG_MAX].rstrip("-")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        slug = re.sub(r"[^a-z0-9-]", "", fallback) or "piece"
    return slug


# Front matter ---------------------------------------------------------------------------

def render_piece(meta, body):
    lines = [_FENCE] + [f"{key}: {json.dumps(value, ensure_ascii=False)}"
                        for key, value in meta.items()] + [_FENCE]
    return "\n".join(lines) + "\n" + body


def _value(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse_piece(text):
    """(front matter dict, body). Raises PieceError."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != _FENCE:
        raise PieceError("no front matter (the file must start with ---)")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == _FENCE)
    except StopIteration:
        raise PieceError("front matter is not closed with ---") from None
    meta = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, raw = line.partition(":")
        if not sep or not key.strip():
            raise PieceError(f"front matter line is not `key: value`: {line[:60]!r}")
        meta[key.strip()] = _value(raw.strip())
    return meta, "\n".join(lines[end + 1:])


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        raise PieceError(f"piece file not found: {to_posix(path)}") from None
    except OSError as exc:
        raise PieceError(f"cannot read {to_posix(path)}: {exc}") from None


def _write_text(path, text, exclusive=False):
    """Atomic replace through a temp file; `exclusive` refuses an existing file."""
    if exclusive:
        with open(path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


# Index ----------------------------------------------------------------------------------

def _empty_index(date):
    return {"schemaVersion": INDEX_VERSION, "date": date, "updatedAt": None, "pieces": [],
            "runs": []}


def load_index(directory, date):
    """Index dict of one inbox, or a new empty one. Raises PieceError when unreadable."""
    path = os.path.join(directory, INDEX_NAME)
    if not os.path.exists(path):
        return _empty_index(date)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PieceError(f"inbox index unreadable: {to_posix(path)} ({exc})") from None
    if (not isinstance(data, dict) or data.get("schemaVersion") != INDEX_VERSION
            or not isinstance(data.get("pieces"), list) or not isinstance(data.get("runs"), list)):
        raise PieceError(f"inbox index has an unsupported shape: {to_posix(path)}")
    return data


def _save_index(directory, index, updated_at):
    index["updatedAt"] = updated_at
    _write_text(os.path.join(directory, INDEX_NAME),
                json.dumps(index, indent=2, ensure_ascii=False) + "\n")


def _next_numbers(directory, index):
    """{audience: highest number used} from the index and the files on disk."""
    used = {a: 0 for a in AUDIENCES}
    for entry in index["pieces"]:
        try:
            _, audience, n = parse_piece_id(entry.get("id"))
        except PieceError:
            continue
        used[audience] = max(used[audience], n)
    for name in os.listdir(directory) if os.path.isdir(directory) else []:
        match = _FILE.match(name)
        if match and match.group(1) in used:
            used[match.group(1)] = max(used[match.group(1)], int(match.group(2)))
    return used


def _source_threads(ids, threads):
    out = []
    for tid in ids:
        t = threads.get(tid) or {}
        out.append({"id": tid, "title": t.get("title"), "project": t.get("project")})
    return out


def add_run(directory, date, run, results, threads):
    """Write the kept pieces of every audience and append the run to the index.

    `results` maps audience -> run_audience result; `threads` maps thread id ->
    {title, project} for the index. A same-day rerun adds new numbers after the existing
    ones and never overwrites a file. Returns the new index entries. Raises PieceError
    (unreadable index) or OSError.
    """
    index = load_index(directory, date)
    os.makedirs(directory, exist_ok=True)
    used = _next_numbers(directory, index)
    created, audiences = [], {}
    for audience, result in results.items():
        kept_ids = []
        for piece in result["kept"]:
            used[audience] += 1
            n = used[audience]
            piece_id = f"{date}-{audience}-{n}"
            meta = {"id": piece_id, "audience": audience,
                    "visibility": AUDIENCES[audience]["visibility"], "status": "proposed",
                    "title": piece["title"], "summary": piece["summary"],
                    "sourceThreadIds": list(piece["sourceThreadIds"]),
                    "relevance": piece["relevance"], "rationale": piece["rationale"],
                    "generatedAt": run["generatedAt"], "model": run["model"]}
            name = f"{audience}-{n}.md"
            body = f"# {piece['title']}\n\n{piece['body'].strip()}\n"
            _write_text(os.path.join(directory, name), render_piece(meta, body), exclusive=True)
            entry = dict(meta, file=name,
                         sourceThreads=_source_threads(meta["sourceThreadIds"], threads),
                         publishedPath=None, decidedAt=None)
            index["pieces"].append(entry)
            created.append(entry)
            kept_ids.append(piece_id)
        audiences[audience] = {"status": result["status"], "warnings": list(result["warnings"]),
                               "candidates": result["candidates"], "kept": kept_ids,
                               "rejected": list(result["rejected"])}
    index["runs"].append(dict(run, audiences=audiences))
    _save_index(directory, index, run["generatedAt"])
    return created


# Listing and decisions ------------------------------------------------------------------

def list_pieces(out_dir, status=None):
    """Index entries of every inbox, newest date first, then index order."""
    root = os.path.join(out_dir, *INBOX_PARTS)
    if not os.path.isdir(root):
        return []
    entries = []
    for date in sorted((d for d in os.listdir(root) if _valid_date(d)), reverse=True):
        directory = os.path.join(root, date)
        if not os.path.isfile(os.path.join(directory, INDEX_NAME)):
            continue
        for entry in load_index(directory, date)["pieces"]:
            if isinstance(entry, dict) and (status is None or entry.get("status") == status):
                entries.append(entry)
    return entries


def _load_piece(out_dir, piece_id):
    date, audience, n = parse_piece_id(piece_id)
    directory = inbox_dir(out_dir, date)
    path = os.path.join(directory, f"{audience}-{n}.md")
    meta, body = parse_piece(_read(path))
    if meta.get("id") != piece_id:
        raise PieceError(f"front matter id does not match {piece_id}: {to_posix(path)}")
    status = meta.get("status")
    if status != "proposed":
        raise PieceError(f"{piece_id} is {status}, only proposed pieces can be decided")
    return date, audience, n, directory, path, meta, body


def _update_index(directory, date, piece_id, decided_at, **fields):
    """Update the entry of piece_id when the index has it; a missing index is skipped."""
    decided_at = decided_at or datetime.now(timezone.utc).isoformat()
    if not os.path.isfile(os.path.join(directory, INDEX_NAME)):
        return
    index = load_index(directory, date)
    for entry in index["pieces"]:
        if isinstance(entry, dict) and entry.get("id") == piece_id:
            entry.update(fields, decidedAt=decided_at)
    _save_index(directory, index, decided_at)


def _destination(publish_dir, audience, date, slug):
    folder = os.path.join(publish_dir, audience)
    os.makedirs(folder, exist_ok=True)
    candidate, k = os.path.join(folder, f"{date}-{slug}.md"), 1
    while os.path.exists(candidate):
        k += 1
        candidate = os.path.join(folder, f"{date}-{slug}-{k}.md")
    return candidate


def approve(out_dir, piece_id, publish_dir, check=None, decided_at=None):
    """Copy the current file to `<publish_dir>/<audience>/<date>-<slug>.md`, set approved.

    External pieces re-run `check(texts) -> [rule]` on the current text (the user may have
    edited it) and are refused when it fails. Returns the published path.
    """
    date, audience, n, directory, path, meta, body = _load_piece(out_dir, piece_id)
    if is_external(audience):
        if check is None:
            raise ValueError(f"{audience} is external: a sanitization check is required")
        texts = [meta.get(k) for k in ("title", "summary", "rationale")] + [body]
        rules = check([t if isinstance(t, str) else json.dumps(t) for t in texts
                       if t is not None])
        if rules:
            raise PieceError(f"refused: {piece_id} fails the sanitization check "
                             f"({', '.join(rules)})")
    meta["status"] = "approved"
    text = render_piece(meta, body)
    slug = slugify(meta.get("title"), f"{audience}-{n}")
    while True:
        target = _destination(publish_dir, audience, date, slug)
        try:
            _write_text(target, text, exclusive=True)
            break
        except FileExistsError:  # created between the check and the write
            continue
    _write_text(path, text)
    _update_index(directory, date, piece_id, decided_at, status="approved",
                  publishedPath=to_posix(target), title=meta.get("title"),
                  summary=meta.get("summary"))
    return target


def discard(out_dir, piece_id, decided_at=None):
    """Set `status: discarded` in the file and the index."""
    date, _, _, directory, path, meta, body = _load_piece(out_dir, piece_id)
    meta["status"] = "discarded"
    _write_text(path, render_piece(meta, body))
    _update_index(directory, date, piece_id, decided_at, status="discarded")
