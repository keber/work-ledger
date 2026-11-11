import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from tests.curatefixtures import LEDGER_AT, NOW, curate_ledger, output, piece, thread
from tests.digestfixtures import previous, project
from work_ledger import cli
from work_ledger.curate_claude import ClaudeError, ClaudeReply
from work_ledger.pieces_store import parse_piece

DATE = NOW.astimezone().date().isoformat()


def capture(fn, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        try:
            value = fn(*args, **kwargs)
        except SystemExit as exc:
            value = exc.code
    return value, out.getvalue(), err.getvalue()


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


class Port:
    """Fake claude port: one reply (or error) per audience, keyed by the input audience."""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, system_prompt, schema, input_text):
        audience = json.loads(input_text)["audience"]
        self.calls.append(audience)
        reply = self.replies.get(audience, output())
        if isinstance(reply, Exception):
            raise reply
        return ClaudeReply(reply, [])


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.denylist = os.path.join(self.tmp.name, "curation-denylist.txt")
        patcher = mock.patch.object(cli, "_now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        write_json(os.path.join(self.out, "ledger.json"), curate_ledger(
            [thread("a", title="Pipeline"),
             thread("old", "stale", last_at="2026-09-01T10:00:00+00:00"),
             thread("d", "discarded")],
            [project("p-app", "work-ledger")]))

    def inbox(self, *parts):
        return os.path.join(self.out, "pieces", "inbox", DATE, *parts)

    def curate(self, *extra, port=None):
        return capture(cli.curate_command, out_dir=self.out, denylist=self.denylist,
                       port=port, **dict(extra))


class CurateDryRunTest(CliCase):
    def test_writes_input_per_audience_and_calls_nothing(self):
        port = Port({})
        (code, count), stdout, err = self.curate(("dry_run", True), port=port)
        self.assertEqual((code, count), (0, 0), err)
        self.assertEqual(port.calls, [])
        for audience in ("portfolio", "team", "public"):
            with open(self.inbox(f"input-{audience}.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["audience"], audience)
            self.assertEqual([t["id"] for t in data["threads"]], ["a"])
        self.assertFalse(os.path.exists(self.inbox("index.json")))
        self.assertIn("1 threads", stdout)

    def test_previous_digest_adds_changed_threads(self):
        write_json(os.path.join(self.out, "digest", "latest.json"),
                   previous({"old": "open", "a": "open"}))
        (code, _), _, err = self.curate(("dry_run", True), ("audiences", ["team"]))
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.inbox("input-public.json")))
        with open(self.inbox("input-team.json"), encoding="utf-8") as fh:
            self.assertEqual([t["id"] for t in json.load(fh)["threads"]], ["a", "old"])

    def test_corrupt_digest_is_a_warning(self):
        write_json(os.path.join(self.out, "digest", "latest.json"), {"schemaVersion": 9})
        (code, _), _, err = self.curate(("dry_run", True))
        self.assertEqual(code, 0, err)
        self.assertIn("warning: previous digest ignored", err)


class CurateRunTest(CliCase):
    def test_writes_proposals_and_returns_the_count(self):
        port = Port({"team": output(piece("Avance", sources=("a",), relevance=0.9)),
                     "public": output(piece("En work-ledger"), piece("Lecciones"))})
        (code, count), stdout, err = self.curate(port=port)
        self.assertEqual((code, count), (0, 2), err)
        self.assertEqual(port.calls, ["portfolio", "team", "public"])
        with open(self.inbox("index.json"), encoding="utf-8") as fh:
            index = json.load(fh)
        self.assertEqual([p["id"] for p in index["pieces"]],
                         [f"{DATE}-team-1", f"{DATE}-public-1"])
        self.assertEqual(index["pieces"][1]["title"], "Lecciones")
        rejected = index["runs"][0]["audiences"]["public"]["rejected"]
        self.assertEqual(rejected, [{"candidate": 1, "reason": "sanitization",
                                     "rules": ["project-name"]}])
        run = index["runs"][0]
        self.assertEqual(run["ledgerGeneratedAt"], LEDGER_AT)
        self.assertEqual(run["input"]["droppedByCap"], 0)
        self.assertIn("2 proposals", stdout)

    def test_denylist_and_company_terms(self):
        with open(self.denylist, "w", encoding="utf-8") as fh:
            fh.write("ClienteSecreto\n")
        port = Port({"public": output(piece("Para clientesecreto"), piece("Acme rocks"),
                                      piece("Limpio"))})
        (code, count), _, err = self.curate(("audiences", ["public"]),
                                            ("company", ["acme"]), port=port)
        self.assertEqual((code, count), (0, 1), err)
        with open(self.inbox("index.json"), encoding="utf-8") as fh:
            index = json.load(fh)
        self.assertEqual(index["pieces"][0]["title"], "Limpio")
        rules = [r["rules"] for r in index["runs"][0]["audiences"]["public"]["rejected"]]
        self.assertEqual(rules, [["denylist"], ["company"]])

    def test_warns_when_no_company_terms_are_configured(self):
        port = Port({"public": output(piece("Limpio"))})
        (code, _), _, err = self.curate(("audiences", ["public"]), port=port)
        self.assertEqual(code, 0, err)
        self.assertIn("warning: public sanitization has no company terms configured", err)
        (code, _), _, err = self.curate(("audiences", ["public"]), ("company", ["acme"]),
                                        port=port)
        self.assertNotIn("no company terms", err)

    def test_failed_audience_does_not_stop_the_others(self):
        port = Port({"portfolio": ClaudeError("timed out after 300 s"),
                     "team": output(piece())})
        (code, count), _, err = self.curate(port=port)
        self.assertEqual((code, count), (1, 1))
        self.assertEqual(port.calls, ["portfolio", "team", "public"])
        self.assertIn("warning: portfolio skipped: claude: timed out", err)

    def test_missing_ledger(self):
        os.remove(os.path.join(self.out, "ledger.json"))
        (code, count), _, err = self.curate(port=Port({}))
        self.assertEqual((code, count), (1, None))
        self.assertIn("ledger: file not found", err)

    def test_claude_not_found(self):
        with mock.patch("work_ledger.curate_claude.shutil.which", return_value=None):
            (code, count), _, err = self.curate()
        self.assertEqual((code, count), (1, None))
        self.assertIn("--claude", err)

    def test_explicit_claude_path_builds_the_real_port(self):
        with mock.patch.object(cli, "claude_port", return_value=Port({})) as factory:
            (code, _), _, err = self.curate(("claude", "D:/bin/claude.exe"))
        self.assertEqual(code, 0, err)
        factory.assert_called_once_with("D:/bin/claude.exe")

    def test_main_dispatch(self):
        with mock.patch.object(cli, "curate_command", return_value=(0, 3)) as spy:
            code, _, _ = capture(cli.main, ["curate", "--out", "D:/o", "--audience", "team",
                                            "public", "--dry-run", "--claude", "C:/c.exe"])
        self.assertEqual(code, 0)
        kwargs = spy.call_args.kwargs
        self.assertEqual(kwargs["audiences"], ["team", "public"])
        self.assertTrue(kwargs["dry_run"])
        self.assertEqual((kwargs["out_dir"], kwargs["claude"]), ("D:/o", "C:/c.exe"))

    def write_config(self, text):
        path = os.path.join(self.tmp.name, "wl.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_main_reads_company_terms_and_claude_from_the_config(self):
        path = self.write_config('[curation]\ncompany_terms = ["acme"]\n'
                                 'claude = "D:/cfg/claude.exe"\n')
        with mock.patch.object(cli, "curate_command", return_value=(0, 0)) as spy:
            capture(cli.main, ["curate", "--config", path])
        kwargs = spy.call_args.kwargs
        self.assertEqual((kwargs["company"], kwargs["claude"]), (("acme",), "D:/cfg/claude.exe"))

    def test_main_cli_flags_win_over_environment_and_config(self):
        path = self.write_config('[curation]\ncompany_terms = ["acme"]\n')
        env = {"WORK_LEDGER_CONFIG": path, "WORK_LEDGER_COMPANY_TERMS": "globex",
               "WORK_LEDGER_CLAUDE": "D:/env/claude.exe"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(cli, "curate_command", return_value=(0, 0)) as spy:
            capture(cli.main, ["curate"])
            self.assertEqual(spy.call_args.kwargs["company"], ("globex",))
            self.assertEqual(spy.call_args.kwargs["claude"], "D:/env/claude.exe")
            capture(cli.main, ["curate", "--company", "initech", "--claude", "D:/c.exe"])
            self.assertEqual(spy.call_args.kwargs["company"], ("initech",))
            self.assertEqual(spy.call_args.kwargs["claude"], "D:/c.exe")

    def test_invalid_or_missing_config_is_a_usage_error(self):
        bad = self.write_config("[curation\n")
        for path in (bad, os.path.join(self.tmp.name, "absent.toml")):
            with mock.patch.object(cli, "curate_command") as spy:
                code, _, err = capture(cli.main, ["curate", "--config", path])
            self.assertEqual(code, 2)
            self.assertIn("error:", err)
            spy.assert_not_called()

    def test_unknown_audience_is_a_usage_error(self):
        code, _, err = capture(cli.main, ["curate", "--audience", "everyone"])
        self.assertEqual(code, 2)


class PiecesCommandTest(CliCase):
    def setUp(self):
        super().setUp()
        self.publish = os.path.join(self.tmp.name, "published")
        port = Port({"team": output(piece("Avance")), "public": output(piece("Lecciones"))})
        (code, _), _, err = self.curate(port=port)
        self.assertEqual(code, 0, err)

    def main(self, *argv):
        return capture(cli.main, ["pieces", *argv, "--out", self.out])

    def test_list_and_filter(self):
        code, stdout, _ = self.main("list")
        self.assertEqual(code, 0)
        self.assertIn(f"{DATE}-team-1", stdout)
        self.assertIn("Lecciones", stdout)
        self.main("discard", f"{DATE}-team-1")
        code, stdout, _ = self.main("list", "--status", "proposed")
        self.assertNotIn(f"{DATE}-team-1", stdout)
        self.assertIn(f"{DATE}-public-1", stdout)

    def test_approve_with_publish_dir(self):
        code, stdout, err = self.main("approve", f"{DATE}-team-1", "--publish-dir",
                                      self.publish)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(os.path.join(self.publish, "team",
                                                    f"{DATE}-avance.md")))
        self.assertIn("approved", stdout)

    def test_publish_dir_from_environment(self):
        with mock.patch.dict(os.environ, {"WORK_LEDGER_PUBLISH_DIR": self.publish}):
            code, _, err = self.main("approve", f"{DATE}-team-1")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isdir(os.path.join(self.publish, "team")))

    def test_publish_dir_from_config_file(self):
        path = os.path.join(self.tmp.name, "wl.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"[curation]\npublish_dir = '{self.publish}'\n")
        code, _, err = self.main("approve", f"{DATE}-team-1", "--config", path)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isdir(os.path.join(self.publish, "team")))

    def test_default_publish_dir(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("os.path.expanduser", side_effect=lambda p: p.replace("~", "H:")):
            self.assertEqual(cli.default_publish_dir(),
                             os.path.join("H:", "Documents", "work-ledger", "published"))

    def test_public_approval_rechecks_with_ledger_names(self):
        path = self.inbox("public-1.md")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("Hecho en Work-Ledger.\n")
        code, stdout, err = self.main("approve", f"{DATE}-public-1", "--publish-dir",
                                      self.publish, "--denylist", self.denylist)
        self.assertEqual(code, 1)
        self.assertIn("project-name", err)
        self.assertFalse(os.path.exists(self.publish))

    def test_public_approval_prints_the_reminder(self):
        code, stdout, err = self.main("approve", f"{DATE}-public-1", "--publish-dir",
                                      self.publish, "--denylist", self.denylist)
        self.assertEqual(code, 0, err)
        self.assertIn("not proof", stdout)

    def test_public_approval_fails_closed_without_the_ledger(self):
        os.remove(os.path.join(self.out, "ledger.json"))
        code, _, err = self.main("approve", f"{DATE}-public-1", "--publish-dir", self.publish)
        self.assertEqual(code, 1)
        self.assertIn("ledger", err)

    def test_discard_and_errors(self):
        code, _, _ = self.main("discard", f"{DATE}-team-1")
        self.assertEqual(code, 0)
        with open(self.inbox("team-1.md"), encoding="utf-8") as fh:
            self.assertEqual(parse_piece(fh.read())[0]["status"], "discarded")
        code, _, err = self.main("discard", f"{DATE}-team-1")
        self.assertEqual(code, 1)
        self.assertIn("error:", err)
        code, _, err = self.main("approve", "../../etc", "--publish-dir", self.publish)
        self.assertEqual(code, 1)
        self.assertIn("invalid piece id", err)


if __name__ == "__main__":
    unittest.main()
