"""Command line entry point.

`python -m work_ledger inventory|sessions|threads|refresh|digest|notify|curate|pieces|weekly`.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from . import config as settings
from .collect import DEFAULT_IGNORE_UNTRACKED, error_repo, collect_repo
from .config import CLAUDE_ENV, CONFIG_ENV, PUBLISH_ENV, ConfigError
from .curate_build import AUDIENCES, is_external, load_prompt, run_audience
from .curate_claude import MODEL, ClaudeError, claude_port, resolve_claude
from .curate_input import (build_input, input_text, previous_snapshot, project_names,
                           select_threads, thread_facts)
from .curate_sanitize import (DEFAULT_COMPANY_TERMS, DENYLIST_NAME, internal_names,
                              parse_denylist, violations)
from .digest_build import build_digest
from .digest_report import (LATEST_NAME, PREVIOUS_NAME, DigestFileError, load_latest,
                            load_previous, write_digest)
from .discover import discover, to_posix
from .notify import (TOAST_TITLE, ToastError, file_uri, powershell_toaster, summary_text,
                     toast_xml)
from .pieces_store import (STATUSES, PieceError, add_run, approve, discard, inbox_dir,
                           list_pieces, parse_piece_id)
from .report import build_report, write_reports
from .sessions_report import build_sessions_report, write_sessions_reports
from .sessions_scan import CACHE_NAME, scan_sessions
from .threads_build import build_ledger
from .threads_inputs import InputError, check_schema, load_inputs, load_json
from .threads_report import write_ledger

INVENTORY_JSON = "git-inventory.json"
SESSIONS_JSON = "sessions.json"
OVERRIDES_NAME = "overrides.json"
LEDGER_JSON = "ledger.json"
DIGEST_DIR = "digest"
LEDGER_VERSIONS = (2,)
NO_COMPANY_WARNING = ("warning: public sanitization has no company terms configured; set "
                      "[curation] company_terms in work-ledger.local.toml, "
                      "WORK_LEDGER_COMPANY_TERMS or --company")
PUBLIC_REMINDER = ("Passing the sanitization check is not proof of safety: check the published "
                   "text for internal details before sharing it.")


def default_roots():
    home = os.path.expanduser("~")
    return [os.path.join(home, "Proyectos"), os.path.join(home, "source", "repos")]


def default_sessions_source():
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def default_out():
    return os.path.join(_project_root(), "out")


def default_overrides():
    return os.path.join(_project_root(), OVERRIDES_NAME)


def default_denylist():
    return os.path.join(_project_root(), DENYLIST_NAME)


def default_publish_dir():
    """Built-in publish dir, used when no flag, variable or config sets one."""
    return os.path.join(os.path.expanduser("~"), "Documents", "work-ledger", "published")


def _common():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="PATH",
                        help=(f"Settings file. Default: ${CONFIG_ENV}, else "
                              f"<project>/{settings.CONFIG_NAME} when it exists"))
    return common


def _parser():
    parser = argparse.ArgumentParser(prog="work_ledger")
    common = _common()
    sub = parser.add_subparsers(dest="command", required=True)
    add = lambda name, **kw: sub.add_parser(name, parents=[common], **kw)  # noqa: E731
    inv = add("inventory", help="Read-only inventory of git repos, worktrees and branches")
    inv.add_argument("--root", action="append", metavar="PATH",
                     help=(f"Directory to scan (repeatable). Default: ${settings.ROOTS_ENV}, "
                           "else [inventory] roots, else ~/Proyectos and ~/source/repos"))
    inv.add_argument("--out", metavar="DIR", help="Output directory. Default: <project>/out")
    defaults = " ".join(DEFAULT_IGNORE_UNTRACKED)
    inv.add_argument("--ignore-untracked", action="append", metavar="PREFIX", default=[],
                     help=("Untracked path prefix to count apart as ignoredUntracked "
                           f"(repeatable, added to the defaults: {defaults})"))
    ses = add("sessions", help="Read-only scan of Claude Code session transcripts")
    ses.add_argument("--source", metavar="DIR",
                     help="Transcripts root. Default: ~/.claude/projects")
    ses.add_argument("--out", metavar="DIR", help="Output directory. Default: <project>/out")
    ses.add_argument("--full", action="store_true",
                     help="Ignore the parse cache and re-parse every transcript")
    thr = add("threads", help="Join inventory and sessions into work threads (ledger)")
    thr.add_argument("--inventory", metavar="PATH",
                     help=f"Git inventory JSON. Default: <out>/{INVENTORY_JSON}")
    thr.add_argument("--sessions", metavar="PATH",
                     help=f"Sessions JSON. Default: <out>/{SESSIONS_JSON}")
    thr.add_argument("--overrides", metavar="PATH",
                     help=f"Overrides JSON (optional). Default: <project>/{OVERRIDES_NAME}")
    thr.add_argument("--out", metavar="DIR", help="Output directory. Default: <project>/out")
    ref = add("refresh", help="Run inventory, sessions and threads in order")
    ref.add_argument("--out", metavar="DIR", help="Output directory. Default: <project>/out")
    dig = add("digest", help="Refresh, then write the weekly pending-work digest")
    dig.add_argument("--ledger", metavar="PATH", help=f"Ledger JSON. Default: <out>/{LEDGER_JSON}")
    dig.add_argument("--out", metavar="DIR", help="Output directory. Default: <project>/out")
    dig.add_argument("--no-refresh", action="store_true",
                     help="Use the existing ledger instead of running refresh first")
    note = add("notify", help="Show a Windows toast for the latest digest")
    note.add_argument("--digest", metavar="PATH",
                      help=f"Digest record. Default: <project>/out/{DIGEST_DIR}/{LATEST_NAME}")
    cur = add("curate", help="Draft communication pieces about the week's work")
    cur.add_argument("--ledger", metavar="PATH", help=f"Ledger JSON. Default: <out>/{LEDGER_JSON}")
    cur.add_argument("--out", metavar="DIR", help="Output directory. Default: <project>/out")
    cur.add_argument("--audience", action="extend", nargs="+", choices=list(AUDIENCES),
                     metavar="ID", help=f"Audiences to run (default all: {', '.join(AUDIENCES)})")
    cur.add_argument("--claude", metavar="PATH",
                     help=(f"claude executable. Default: ${CLAUDE_ENV}, else [curation] claude, "
                           "else on PATH"))
    cur.add_argument("--dry-run", action="store_true",
                     help="Write the model input per audience and make no model call")
    _add_check_options(cur)
    pcs = sub.add_parser("pieces", help="List, approve or discard proposed pieces")
    psub = pcs.add_subparsers(dest="pieces_command", required=True)
    plist = psub.add_parser("list", parents=[common],
                           help="Print the pieces of every inbox, newest first")
    plist.add_argument("--status", choices=STATUSES, help="Only pieces in this status")
    papp = psub.add_parser("approve", parents=[common],
                          help="Approve a piece and copy it to the publish dir")
    papp.add_argument("id", help="Piece id, YYYY-MM-DD-<audience>-<n>")
    papp.add_argument("--publish-dir", metavar="DIR",
                      help=(f"Default: ${PUBLISH_ENV}, else [curation] publish_dir, "
                            "else ~/Documents/work-ledger/published"))
    _add_check_options(papp)
    pdis = psub.add_parser("discard", parents=[common], help="Discard a piece")
    pdis.add_argument("id", help="Piece id, YYYY-MM-DD-<audience>-<n>")
    for p in (plist, papp, pdis):
        p.add_argument("--out", metavar="DIR", help="Output directory. Default: <project>/out")
    week = add("weekly", help="digest, curate, then notify (what the scheduled task runs)")
    week.add_argument("--out", metavar="DIR", help="Output directory. Default: <project>/out")
    return parser


def _add_check_options(parser):
    parser.add_argument("--company", action="append", metavar="TERM",
                        help=("Company name or domain for the public check (repeatable). "
                              f"Default: ${settings.COMPANY_ENV}, else [curation] "
                              "company_terms, else none"))
    parser.add_argument("--denylist", metavar="PATH",
                        help=f"Denylist for the public check. Default: <project>/{DENYLIST_NAME}")


def _collect_safely(ref, ignore_untracked):
    try:
        return collect_repo(ref, ignore_untracked)
    except Exception as exc:  # one repo must never abort the whole run
        return error_repo(ref, f"{type(exc).__name__}: {exc}")


def inventory(roots, out_dir, ignore_untracked=DEFAULT_IGNORE_UNTRACKED):
    refs = discover(roots)
    repos = [_collect_safely(ref, ignore_untracked) for ref in refs]
    report = build_report(repos, [to_posix(r) for r in roots], ignore_untracked=ignore_untracked)
    return write_reports(report, out_dir), report


def sessions(source, out_dir, full=False, claude_home=None):
    found, stats = scan_sessions(source, os.path.join(out_dir, CACHE_NAME), full=full,
                                 claude_home=claude_home)
    report = build_sessions_report(found, stats, to_posix(source))
    return write_sessions_reports(report, out_dir), report


def _sessions_main(parser, args):
    if args.source and not os.path.isdir(args.source):
        parser.error(f"source is not a directory: {args.source}")
    source = args.source or default_sessions_source()
    out_dir = args.out or default_out()
    try:
        (json_path, md_path), report = sessions(source, out_dir, full=args.full)
    except OSError as exc:
        print(f"error: cannot write output to {out_dir}: {exc}", file=sys.stderr)
        return 1

    stats = report["stats"]
    print(f"{len(report['sessions'])} sessions (parsed={stats['parsed']}, cached={stats['cached']}, "
          f"unreadable={stats['unreadable']}, skipped lines={stats['skippedLines']})")
    print(f"wrote {to_posix(json_path)}")
    print(f"wrote {to_posix(md_path)}")
    return 0


def threads(inventory_path, sessions_path, overrides_path, out_dir, generated_at=None):
    inventory_data, sessions_data, overrides_data = load_inputs(inventory_path, sessions_path,
                                                                overrides_path)
    inputs = {"inventory": to_posix(inventory_path), "sessions": to_posix(sessions_path),
              "overrides": to_posix(overrides_path) if overrides_path else None}
    ledger = build_ledger(inventory_data, sessions_data, overrides_data,
                          generated_at=generated_at, inputs=inputs)
    return write_ledger(ledger, out_dir), ledger


def _threads_main(parser, args):
    missing = [p for p in (args.inventory, args.sessions, args.overrides)
               if p and not os.path.isfile(p)]
    if missing:
        parser.error(f"file not found: {', '.join(missing)}")
    out_dir = args.out or default_out()
    inventory_path = args.inventory or os.path.join(out_dir, INVENTORY_JSON)
    sessions_path = args.sessions or os.path.join(out_dir, SESSIONS_JSON)
    overrides_path = args.overrides or default_overrides()
    try:
        (json_path, md_path), ledger = threads(inventory_path, sessions_path, overrides_path,
                                               out_dir)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot write output to {out_dir}: {exc}", file=sys.stderr)
        return 1

    for warning in ledger["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    states = ", ".join(f"{k}={v}" for k, v in ledger["stats"]["effectiveStates"].items() if v)
    at_risk = sum(1 for p in ledger["projects"] if p["atRisk"])
    print(f"{ledger['stats']['projects']} projects ({at_risk} at risk), "
          f"{ledger['stats']['threads']} threads ({states or 'none'})")
    print(f"wrote {to_posix(json_path)}")
    print(f"wrote {to_posix(md_path)}")
    return 0


REFRESH_STEPS = ("inventory", "sessions", "threads")


def refresh(out_dir=None, steps=None, config=None):
    """Run each step with default arguments (plus --out, --config); stop at the first failure."""
    if steps is None:
        steps = [(name, main) for name in REFRESH_STEPS]
    extra = (["--out", out_dir] if out_dir else []) + (["--config", config] if config else [])
    for name, run in steps:
        try:
            code = run([name, *extra])
        except SystemExit as exc:  # argparse errors exit through SystemExit
            code = exc.code if isinstance(exc.code, int) else 1
        if code:
            return code
    return 0


def _now():
    return datetime.now(timezone.utc)


def _platform():
    return sys.platform


def default_latest(out_dir=None):
    return os.path.join(out_dir or default_out(), DIGEST_DIR, LATEST_NAME)


def digest_command(ledger_path=None, out_dir=None, no_refresh=False, config=None):
    """Refresh (unless no_refresh), then write the digest. Returns the exit code."""
    out = out_dir or default_out()
    if not no_refresh:
        code = refresh(out_dir, config=config)
        if code:
            return code
    ledger_path = ledger_path or os.path.join(out, LEDGER_JSON)
    latest_path = default_latest(out)
    try:
        ledger = check_schema(load_json(ledger_path, "ledger"), "ledger", LEDGER_VERSIONS)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        previous = load_previous(latest_path)
    except DigestFileError as exc:
        print(f"warning: previous digest ignored: {exc}", file=sys.stderr)
        previous = None
    now = _now()
    digest = build_digest(ledger, previous)
    try:
        md_path, written = write_digest(digest, os.path.dirname(latest_path), now,
                                        now.astimezone().date().isoformat())
    except OSError as exc:
        print(f"error: cannot write digest to {os.path.dirname(latest_path)}: {exc}",
              file=sys.stderr)
        return 1
    print(summary_text(digest["counts"]))
    print(f"wrote {to_posix(md_path)}")
    print(f"wrote {to_posix(written)}")
    return 0


def notify_command(latest_path, toaster=None, platform=None, proposals=None):
    """Show the digest toast. Prints the summary; exits 1 off Windows or on any failure."""
    try:
        latest = load_latest(latest_path)
    except DigestFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    summary = summary_text(latest["counts"], proposals)
    print(summary)
    md_path = latest["path"]
    if not os.path.isabs(md_path):
        md_path = os.path.join(os.path.dirname(os.path.abspath(latest_path)), md_path)
    print(f"digest: {to_posix(md_path)}")
    if (platform or _platform()) != "win32":
        print("error: toast notifications need Windows", file=sys.stderr)
        return 1
    if not os.path.isfile(md_path):
        print(f"error: digest file not found: {md_path}", file=sys.stderr)
        return 1
    show = toaster or powershell_toaster
    try:
        show(toast_xml(TOAST_TITLE, summary, file_uri(md_path)))
    except ToastError as exc:
        print(f"error: toast not shown: {exc}", file=sys.stderr)
        return 1
    return 0


def _digest_record(path):
    """A digest record (latest.json or previous.json), or None; problems are warnings."""
    try:
        return load_previous(path)
    except DigestFileError as exc:
        print(f"warning: previous digest ignored: {exc}", file=sys.stderr)
        return None


def _optional_inventory(out_dir):
    path = os.path.join(out_dir, INVENTORY_JSON)
    if not os.path.exists(path):
        return None
    try:
        return load_json(path, "inventory")
    except InputError as exc:
        print(f"warning: inventory names not used in the public check: {exc}", file=sys.stderr)
        return None


def _load_denylist(path):
    """Terms of the user-owned denylist; a missing file is an empty list. Raises OSError."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return parse_denylist(fh.read())


def _public_check(ledger, out_dir, company, denylist_path):
    """check(texts) -> [rule] for external pieces. Raises OSError on an unreadable denylist."""
    names = internal_names(ledger, _optional_inventory(out_dir))
    terms = _load_denylist(denylist_path or default_denylist())
    company = DEFAULT_COMPANY_TERMS if company is None else tuple(company)
    if not company:
        print(NO_COMPANY_WARNING, file=sys.stderr)
    return lambda texts: violations(texts, names=names, company=company, denylist=terms)


def _load_ledger(path):
    return check_schema(load_json(path, "ledger"), "ledger", LEDGER_VERSIONS)


def _thread_titles(ledger):
    names = project_names(ledger)
    return {t["id"]: {"title": t.get("title"), "project": names.get(t.get("projectId"))}
            for t in ledger.get("threads") or [] if isinstance(t, dict) and t.get("id")}


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(input_text(data) + "\n")
    os.replace(tmp, path)


def curate_command(ledger_path=None, out_dir=None, audiences=None, claude=None, dry_run=False,
                   company=None, denylist=None, port=None):
    """Draft pieces per audience. Returns (exit code, proposals written or None).

    Exit 1 when the run cannot start, or when any audience failed; the other audiences
    still run and their proposals are written. The count is None when nothing was written.
    """
    out = out_dir or default_out()
    try:
        ledger = _load_ledger(ledger_path or os.path.join(out, LEDGER_JSON))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1, None
    digest_dir = os.path.join(out, DIGEST_DIR)
    latest = _digest_record(os.path.join(digest_dir, LATEST_NAME))
    rotated = _digest_record(os.path.join(digest_dir, PREVIOUS_NAME))
    snapshot, previous_at = previous_snapshot(ledger, latest, rotated)

    now = _now()
    date = now.astimezone().date().isoformat()
    names = project_names(ledger)
    facts = [thread_facts(t, names) for t in select_threads(ledger, snapshot, now)]
    audiences = list(dict.fromkeys(audiences or AUDIENCES))
    inputs = {a: build_input(facts, a, AUDIENCES[a]["max"], ledger.get("generatedAt"))
              for a in audiences}
    dropped = max((d for _, d in inputs.values()), default=0)
    against = f"digest {previous_at}" if previous_at else "no previous digest"
    print(f"{len(facts)} threads selected ({against}), {dropped} dropped by the input cap")
    inbox = inbox_dir(out, date)

    if dry_run:
        try:
            os.makedirs(inbox, exist_ok=True)
            for audience, (data, _) in inputs.items():
                path = os.path.join(inbox, f"input-{audience}.json")
                _write_json(path, data)
                print(f"wrote {to_posix(path)}")
        except OSError as exc:
            print(f"error: cannot write to {inbox}: {exc}", file=sys.stderr)
            return 1, None
        return 0, 0

    try:
        check = _public_check(ledger, out, company, denylist)
    except OSError as exc:
        print(f"error: cannot read the denylist: {exc}", file=sys.stderr)
        return 1, None
    if port is None:
        try:
            port = claude_port(resolve_claude(claude))
        except ClaudeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1, None

    results = {}
    for audience, (data, cut) in inputs.items():
        result = run_audience(audience, data, port, load_prompt(audience),
                              check=check if is_external(audience) else None)
        result["input"] = {"threads": len(data["threads"]), "droppedByCap": cut,
                           "chars": len(input_text(data))}
        results[audience] = result
        prefix = f"{audience} skipped" if result["status"] == "failed" else audience
        for warning in result["warnings"]:
            print(f"warning: {prefix}: {warning}", file=sys.stderr)
    run = {"generatedAt": now.isoformat(), "ledgerGeneratedAt": ledger.get("generatedAt"),
           "previousDigestGeneratedAt": previous_at, "model": MODEL,
           "input": {"threads": len(facts), "droppedByCap": dropped,
                     "chars": max((r["input"]["chars"] for r in results.values()), default=0)}}
    try:
        created = add_run(inbox, date, run, results, _thread_titles(ledger))
    except (PieceError, OSError) as exc:
        print(f"error: cannot write proposals to {inbox}: {exc}", file=sys.stderr)
        return 1, None
    failed = [a for a, r in results.items() if r["status"] == "failed"]
    skipped = f" ({', '.join(failed)} skipped)" if failed else ""
    print(f"{len(created)} proposals in {to_posix(inbox)}{skipped}")
    return (1 if failed else 0), len(created)


def _relevance_text(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}"
    return "-"


def pieces_list_command(out_dir=None, status=None):
    try:
        entries = list_pieces(out_dir or default_out(), status)
    except PieceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for e in entries:
        print(f"{e.get('id')}  {str(e.get('status')):<9}  {str(e.get('audience')):<9}  "
              f"{_relevance_text(e.get('relevance'))}  {e.get('title')}")
    if not entries:
        print("no pieces")
    return 0


def pieces_approve_command(piece_id, out_dir=None, publish_dir=None, company=None,
                           denylist=None):
    out = out_dir or default_out()
    check = None
    try:
        _, audience, _ = parse_piece_id(piece_id)
        if is_external(audience):
            # Fail closed: without the ledger the project-name rule has nothing to match.
            ledger = _load_ledger(os.path.join(out, LEDGER_JSON))
            check = _public_check(ledger, out, company, denylist)
        target = approve(out, piece_id, publish_dir or default_publish_dir(), check=check)
    except InputError as exc:
        print(f"error: the public check needs the ledger: {exc}", file=sys.stderr)
        return 1
    except (PieceError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"approved {piece_id}: {to_posix(target)}")
    if check is not None:
        print(PUBLIC_REMINDER)
    return 0


def pieces_discard_command(piece_id, out_dir=None):
    try:
        discard(out_dir or default_out(), piece_id)
    except (PieceError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"discarded {piece_id}")
    return 0


def _pieces_main(args, cfg=None):
    if args.pieces_command == "list":
        return pieces_list_command(args.out, args.status)
    if args.pieces_command == "approve":
        company, _ = _curation_settings(args, cfg)
        publish_dir = settings.setting(args.publish_dir, os.environ, PUBLISH_ENV,
                                       cfg.publish_dir)
        return pieces_approve_command(args.id, args.out, publish_dir, company, args.denylist)
    return pieces_discard_command(args.id, args.out)


def weekly(out_dir=None, config=None, company=None, claude=None):
    """digest, then curate, then notify. A failed or crashing curate does not stop notify.

    `config` is the explicit config path handed to refresh; `company` and `claude` are
    already resolved. Returns the digest code when it fails; else notify's code, or
    curate's when notify succeeded.
    """
    code = digest_command(out_dir=out_dir, config=config)
    if code:
        return code
    try:
        curate_code, proposals = curate_command(out_dir=out_dir, company=company, claude=claude)
    except Exception as exc:  # curation must never block the reminder
        print(f"error: curate failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        curate_code, proposals = 1, None
    notify_code = notify_command(default_latest(out_dir), proposals=proposals)
    return notify_code or curate_code


def _load_settings(args):
    """Config from --config, $WORK_LEDGER_CONFIG or the project's local file. Raises ConfigError."""
    path, explicit = settings.config_path(args.config, os.environ, _project_root())
    return settings.load_config(path, explicit)


def _curation_settings(args, cfg):
    """(company terms, claude executable or None), resolved CLI > env > config > default."""
    company = settings.company_terms(getattr(args, "company", None), os.environ, cfg)
    claude = settings.setting(getattr(args, "claude", None), os.environ, CLAUDE_ENV, cfg.claude)
    return company, claude


def _needs_settings(args):
    return args.command in ("inventory", "curate", "weekly") or (
        args.command == "pieces" and args.pieces_command == "approve")


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    cfg = None
    if _needs_settings(args):
        try:
            cfg = _load_settings(args)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.command == "digest":
        return digest_command(args.ledger, args.out, args.no_refresh, config=args.config)
    if args.command == "notify":
        return notify_command(args.digest or default_latest())
    if args.command == "curate":
        company, claude = _curation_settings(args, cfg)
        code, _ = curate_command(ledger_path=args.ledger, out_dir=args.out,
                                 audiences=args.audience, claude=claude,
                                 dry_run=args.dry_run, company=company,
                                 denylist=args.denylist)
        return code
    if args.command == "pieces":
        return _pieces_main(args, cfg)
    if args.command == "weekly":
        company, claude = _curation_settings(args, cfg)
        return weekly(args.out, config=args.config, company=company, claude=claude)
    if args.command == "sessions":
        return _sessions_main(parser, args)
    if args.command == "threads":
        return _threads_main(parser, args)
    if args.command == "refresh":
        return refresh(args.out, config=args.config)

    explicit_roots = settings.roots(args.root, {}, settings.Config(), [])
    if explicit_roots:
        missing = [r for r in explicit_roots if not os.path.isdir(r)]
        if missing:
            parser.error(f"root is not a directory: {', '.join(missing)}")
        roots = explicit_roots
    else:
        configured = settings.roots(None, os.environ, cfg, [])
        roots = [r for r in configured or default_roots() if os.path.isdir(r)]
    out_dir = args.out or default_out()
    ignore_untracked = list(DEFAULT_IGNORE_UNTRACKED) + args.ignore_untracked

    try:
        (json_path, md_path), report = inventory(roots, out_dir, ignore_untracked)
    except OSError as exc:
        print(f"error: cannot write output to {out_dir}: {exc}", file=sys.stderr)
        return 1

    risks = report["summary"]["risks"]
    counts = ", ".join(f"{k}={v}" for k, v in risks.items() if v)
    print(f"{report['summary']['repos']} repos ({counts or 'no items'})")
    print(f"wrote {to_posix(json_path)}")
    print(f"wrote {to_posix(md_path)}")
    return 0
