import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from tests.digestfixtures import NOW, git, ledger, previous, thread
from work_ledger import cli
from work_ledger.notify import ToastError


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def sample_ledger():
    return ledger([thread("a", "at-risk", days=2, git=git("unpushed", 3)),
                   thread("b", "open", days=8, lead="s-b"), thread("c", "stale", days=40)])


class DigestCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "out")
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(cli, "_now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read_latest(self):
        with open(os.path.join(self.out, "digest", "latest.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_no_refresh_reads_out_ledger_and_writes_digest(self):
        write_json(os.path.join(self.out, "ledger.json"), sample_ledger())
        with mock.patch.object(cli, "refresh") as spy:
            code, stdout, err = run_main(["digest", "--out", self.out, "--no-refresh"])
        self.assertEqual(code, 0, err)
        spy.assert_not_called()
        md = os.path.join(self.out, "digest", f"{NOW.astimezone().date().isoformat()}.md")
        self.assertTrue(os.path.isfile(md))
        latest = self.read_latest()
        self.assertEqual(latest["counts"]["atRiskRecent"], 1)
        self.assertEqual(latest["snapshot"], {"a": "at-risk", "b": "open", "c": "stale"})
        self.assertIn("1 at risk (recent), 1 going cold, 3 commits on no remote", stdout)
        self.assertIn("wrote", stdout)

    def test_refresh_runs_first_with_out(self):
        write_json(os.path.join(self.out, "ledger.json"), sample_ledger())
        with mock.patch.object(cli, "refresh", return_value=0) as spy:
            code, _, err = run_main(["digest", "--out", self.out])
        self.assertEqual(code, 0, err)
        spy.assert_called_once_with(self.out, config=None)

    def test_refresh_failure_stops_with_its_code(self):
        with mock.patch.object(cli, "refresh", return_value=4):
            code, _, _ = run_main(["digest", "--out", self.out])
        self.assertEqual(code, 4)
        self.assertFalse(os.path.exists(os.path.join(self.out, "digest")))

    def test_explicit_ledger_path(self):
        path = write_json(os.path.join(self.tmp.name, "elsewhere", "l.json"), sample_ledger())
        code, _, err = run_main(["digest", "--ledger", path, "--out", self.out,
                                 "--no-refresh"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read_latest()["counts"]["goingCold"], 1)

    def test_previous_snapshot_is_used(self):
        write_json(os.path.join(self.out, "ledger.json"), sample_ledger())
        write_json(os.path.join(self.out, "digest", "latest.json"), previous({"c": "open"}))
        code, _, err = run_main(["digest", "--out", self.out, "--no-refresh"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read_latest()["counts"]["wentStale"], 1)

    def test_corrupt_previous_is_a_warning(self):
        write_json(os.path.join(self.out, "ledger.json"), sample_ledger())
        write_json(os.path.join(self.out, "digest", "latest.json"), {"schemaVersion": 7})
        code, _, err = run_main(["digest", "--out", self.out, "--no-refresh"])
        self.assertEqual(code, 0, err)
        self.assertIn("warning:", err)
        self.assertIsNone(self.read_latest()["counts"]["wentStale"])

    def test_missing_ledger_exits_1(self):
        code, _, err = run_main(["digest", "--out", self.out, "--no-refresh"])
        self.assertEqual(code, 1)
        self.assertIn("ledger: file not found", err)

    def test_unsupported_ledger_schema_exits_1(self):
        write_json(os.path.join(self.out, "ledger.json"), ledger(version=1))
        code, _, err = run_main(["digest", "--out", self.out, "--no-refresh"])
        self.assertEqual(code, 1)
        self.assertIn("unsupported schemaVersion 1", err)

    def test_unwritable_output_exits_1(self):
        write_json(os.path.join(self.out, "ledger.json"), sample_ledger())
        with open(os.path.join(self.out, "digest"), "w", encoding="utf-8") as fh:
            fh.write("a file, not a directory")
        code, _, err = run_main(["digest", "--out", self.out, "--no-refresh"])
        self.assertEqual(code, 1)
        self.assertIn("cannot write digest", err)


class NotifyCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.md = os.path.join(self.tmp.name, "2026-11-06.md")
        with open(self.md, "w", encoding="utf-8") as fh:
            fh.write("# d\n")
        self.latest = write_json(os.path.join(self.tmp.name, "latest.json"), {
            "schemaVersion": 1, "generatedAt": NOW.isoformat(), "ledgerGeneratedAt": "x",
            "path": self.md.replace("\\", "/"),
            "counts": {"atRiskRecent": 1, "goingCold": 2, "notOnRemoteCommits": 3},
            "snapshot": {}})
        self.shown = []

    def toaster(self, xml):
        self.shown.append(xml)

    def run_notify(self, latest=None, toaster=None, platform="win32"):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = cli.notify_command(latest or self.latest, toaster=toaster or self.toaster,
                                      platform=platform)
        return code, out.getvalue(), err.getvalue()

    def test_shows_toast_with_counts_and_launch_uri(self):
        code, stdout, err = self.run_notify()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.shown), 1)
        self.assertIn("Work ledger: weekly digest", self.shown[0])
        self.assertIn("1 at risk (recent), 2 going cold, 3 commits on no remote", self.shown[0])
        self.assertIn('launch="file:///', self.shown[0])
        self.assertIn("2026-11-06.md", self.shown[0])
        self.assertIn("1 at risk (recent)", stdout)

    def test_proposal_count_is_added_to_the_toast(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = cli.notify_command(self.latest, toaster=self.toaster, platform="win32",
                                      proposals=4)
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("4 pieces to review", self.shown[0])

    def test_non_windows_prints_summary_and_exits_1(self):
        code, stdout, err = self.run_notify(platform="linux")
        self.assertEqual(code, 1)
        self.assertEqual(self.shown, [])
        self.assertIn("1 at risk (recent)", stdout)
        self.assertIn("Windows", err)

    def test_toast_failure_prints_summary_and_exits_1(self):
        def failing(xml):
            raise ToastError("PowerShell timed out after 30 s")
        code, stdout, err = self.run_notify(toaster=failing)
        self.assertEqual(code, 1)
        self.assertIn("1 at risk (recent)", stdout)
        self.assertIn("timed out", err)

    def test_missing_latest_exits_1(self):
        code, _, err = self.run_notify(latest=os.path.join(self.tmp.name, "none.json"))
        self.assertEqual(code, 1)
        self.assertIn("file not found", err)

    def test_invalid_latest_exits_1(self):
        bad = write_json(os.path.join(self.tmp.name, "bad.json"), {"schemaVersion": 1})
        code, _, err = self.run_notify(latest=bad)
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_missing_markdown_exits_1(self):
        os.remove(self.md)
        code, stdout, err = self.run_notify()
        self.assertEqual(code, 1)
        self.assertEqual(self.shown, [])
        self.assertIn("digest file not found", err)
        self.assertIn("1 at risk (recent)", stdout)

    def test_cli_dispatches_notify_with_default_path(self):
        with mock.patch.object(cli, "notify_command", return_value=0) as spy:
            code, _, _ = run_main(["notify"])
        self.assertEqual(code, 0)
        self.assertEqual(os.path.normcase(spy.call_args.args[0]),
                         os.path.normcase(os.path.join(cli.default_out(), "digest",
                                                       "latest.json")))
        with mock.patch.object(cli, "notify_command", return_value=1) as spy:
            code, _, _ = run_main(["notify", "--digest", "D:/x/latest.json"])
        self.assertEqual(code, 1)
        self.assertEqual(spy.call_args.args[0], "D:/x/latest.json")

    def test_default_toaster_is_powershell(self):
        with mock.patch.object(cli, "powershell_toaster") as spy:
            out, errs = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(errs), contextlib.redirect_stdout(out):
                code = cli.notify_command(self.latest, platform="win32")
        self.assertEqual(code, 0, errs.getvalue())
        spy.assert_called_once()


class WeeklyCommandTest(unittest.TestCase):
    def patched(self, digest=0, curate=(0, 2), notify=0):
        calls = []

        def record(name, value):
            def side_effect(*args, **kwargs):
                calls.append((name, args, kwargs))
                if isinstance(value, Exception):
                    raise value
                return value
            return side_effect
        patches = [mock.patch.object(cli, "digest_command", side_effect=record("digest", digest)),
                   mock.patch.object(cli, "curate_command", side_effect=record("curate", curate)),
                   mock.patch.object(cli, "notify_command", side_effect=record("notify", notify))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return calls

    def test_digest_then_curate_then_notify_with_the_proposal_count(self):
        calls = self.patched()
        code, _, _ = run_main(["weekly", "--out", "D:/o"])
        self.assertEqual(code, 0)
        self.assertEqual([c[0] for c in calls], ["digest", "curate", "notify"])
        self.assertEqual(calls[1][2].get("out_dir"), "D:/o")
        self.assertEqual(calls[2][2].get("proposals"), 2)

    def test_config_reaches_digest_and_curate(self):
        calls = self.patched()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "wl.toml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('[curation]\ncompany_terms = ["acme"]\nclaude = "D:/c.exe"\n')
            run_main(["weekly", "--config", path])
        self.assertEqual(calls[0][2].get("config"), path)
        self.assertEqual((calls[1][2].get("company"), calls[1][2].get("claude")),
                         (("acme",), "D:/c.exe"))

    def test_digest_failure_skips_curate_and_notify(self):
        calls = self.patched(digest=3)
        code, _, _ = run_main(["weekly"])
        self.assertEqual(code, 3)
        self.assertEqual([c[0] for c in calls], ["digest"])

    def test_curate_failure_does_not_stop_notify(self):
        calls = self.patched(curate=(1, None))
        code, _, _ = run_main(["weekly"])
        self.assertEqual([c[0] for c in calls], ["digest", "curate", "notify"])
        self.assertIsNone(calls[2][2].get("proposals"))
        self.assertEqual(code, 1)

    def test_partial_curate_failure_still_reports_its_proposals(self):
        calls = self.patched(curate=(1, 2))
        code, _, _ = run_main(["weekly"])
        self.assertEqual(calls[2][2].get("proposals"), 2)
        self.assertEqual(code, 1)

    def test_curate_crash_does_not_stop_notify(self):
        calls = self.patched(curate=RuntimeError("boom"))
        code, _, err = run_main(["weekly"])
        self.assertEqual([c[0] for c in calls], ["digest", "curate", "notify"])
        self.assertIn("curate failed", err)
        self.assertEqual(code, 1)

    def test_notify_exit_code_is_returned(self):
        self.patched(notify=1)
        code, _, _ = run_main(["weekly"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
