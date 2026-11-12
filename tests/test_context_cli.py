import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from tests.contextfixtures import NOW, ledger, project, thread
from tests.gitfixtures import Sandbox
from tests.sessionfixtures import assistant_text, tool, tool_result, user, write_jsonl
from work_ledger import cli


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


def snapshot(root):
    found = {}
    for folder, _, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            found[path] = os.path.getmtime(path)
    return found


class ContextCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        patcher = mock.patch.object(cli, "_now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.transcript = write_jsonl(
            os.path.join(self.tmp.name, "projects", "p", "s-1.jsonl"),
            user("migrate the export module to the new API", ts="2026-11-09T10:00:00Z"),
            tool("Bash", {"command": "cat config.ini"}, ts="2026-11-09T10:00:01Z"),
            tool_result(ts="2026-11-09T10:00:02Z"),
            assistant_text("Half done: the client is migrated, tests pending.",
                           ts="2026-11-09T10:10:00Z"))
        self.ledger_path = self.write_ledger("C:/no/such/folder/shop")

    def write_ledger(self, project_path, sessions_path=None, transcript=None, source=None):
        sessions_path = sessions_path or os.path.join(self.out, "sessions.json")
        report = {
            "schemaVersion": 3, "generatedAt": "2026-11-11T08:00:00+00:00",
            "sourceRoot": (source or os.path.join(self.tmp.name, "projects")).replace("\\", "/"),
            "sessions": [
                {"sessionId": "s-1",
                 "transcriptPath": (transcript or self.transcript).replace("\\", "/"),
                 "firstAt": "2026-11-09T10:00:00Z", "lastAt": "2026-11-09T10:10:00Z",
                 "entrypoint": "claude-desktop", "userMessages": 1,
                 "lastPrompt": "migrate the export module to the new API"}]}
        if source is False:
            del report["sourceRoot"]
        write_json(sessions_path, report)
        data = ledger(
            [project("p-shop", "Shop_Exportadora", path=project_path, at_risk=True,
                     last_at="2026-11-09T10:10:00Z", threads=["t1", "t2"]),
             project("p-blog", "blog", last_at="2026-09-01T10:00:00Z")],
            [thread("t1", title="Export API migration", sessions=["s-1"],
                    last_at="2026-11-09T10:10:00Z", recap="Client migrated; tests pending."),
             thread("t2", title="worktree-agent-ab12", sessions=[],
                    last_at="2026-11-01T10:00:00Z")],
            sessions_path=sessions_path.replace("\\", "/"))
        return write_json(os.path.join(self.out, "ledger.json"), data)

    def test_query_prints_markdown_with_git_threads_and_excerpts(self):
        code, stdout, err = run_main(["context", "exportadora", "--ledger", self.ledger_path])
        self.assertEqual(code, 0, err)
        self.assertIn('# Work context: "exportadora"', stdout)
        self.assertIn("Shop_Exportadora", stdout)
        self.assertIn("path not found", stdout)
        self.assertIn("Export API migration", stdout)
        self.assertIn("1 threads without sessions", stdout)
        self.assertIn("user: migrate the export module to the new API", stdout)
        self.assertIn("assistant: Half done: the client is migrated, tests pending.", stdout)
        self.assertIn("`claude --resume s-1`", stdout)
        self.assertNotIn("config.ini", stdout)
        self.assertNotIn("blog", stdout)

    def test_json(self):
        code, stdout, err = run_main(["context", "export", "--ledger", self.ledger_path,
                                      "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(stdout)
        self.assertEqual(data["schemaVersion"], 1)
        excerpts = data["projects"][0]["threads"][0]["excerpts"]
        self.assertEqual(excerpts[0]["entries"][0]["role"], "user")
        self.assertEqual(data["projects"][0]["git"]["status"], "missing")

    def test_default_ledger_is_out_ledger(self):
        with mock.patch.object(cli, "default_out", return_value=self.out):
            code, stdout, err = run_main(["context", "shop"])
        self.assertEqual(code, 0, err)
        self.assertIn("Shop_Exportadora", stdout)

    def test_sessions_json_next_to_ledger_when_recorded_path_is_gone(self):
        self.write_ledger("C:/no/such", sessions_path=os.path.join(self.out, "sessions.json"))
        with open(self.ledger_path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["inputs"]["sessions"]["path"] = "C:/gone/sessions.json"
        write_json(self.ledger_path, data)
        code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertEqual(code, 0, err)
        self.assertIn("migrate the export module", stdout)

    def test_missing_sessions_report_is_a_note(self):
        os.remove(os.path.join(self.out, "sessions.json"))
        code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertEqual(code, 0, err)
        self.assertIn("transcript excerpts unavailable", stdout)

    def test_no_match_prints_closest_and_exits_1(self):
        code, stdout, _ = run_main(["context", "blgo-x", "--ledger", self.ledger_path])
        self.assertEqual(code, 1)
        self.assertIn('No project matches "blgo-x"', stdout)
        self.assertIn("blog", stdout)

    def test_overview_without_query(self):
        code, stdout, err = run_main(["context", "--ledger", self.ledger_path])
        self.assertEqual(code, 0, err)
        self.assertIn("overview", stdout)
        self.assertIn("Shop_Exportadora", stdout)
        self.assertIn("AT RISK", stdout)
        self.assertIn("Export API migration", stdout)
        self.assertNotIn("blog", stdout)

    def test_missing_ledger(self):
        code, _, err = run_main(["context", "x", "--ledger", os.path.join(self.tmp.name, "n.json")])
        self.assertEqual(code, 1)
        self.assertIn("--refresh", err)

    def test_refresh_runs_first_and_keeps_stdout_clean(self):
        def fake_refresh(out_dir=None, config=None):
            print("wrote something")
            return 0

        with mock.patch.object(cli, "refresh", side_effect=fake_refresh) as spy:
            code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path,
                                          "--refresh", "--json"])
        self.assertEqual(code, 0, err)
        spy.assert_called_once_with(None, config=None)
        json.loads(stdout)
        self.assertIn("wrote something", err)

    def test_refresh_failure_stops(self):
        with mock.patch.object(cli, "refresh", return_value=3):
            code, stdout, _ = run_main(["context", "shop", "--ledger", self.ledger_path,
                                        "--refresh"])
        self.assertEqual(code, 3)
        self.assertEqual(stdout, "")

    def test_max_chars_truncates_with_note(self):
        code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path,
                                      "--max-chars", "900"])
        self.assertEqual(code, 0, err)
        self.assertLessEqual(len(stdout.rstrip("\n")), 900)
        self.assertIn("Output truncated", stdout)

    def test_transcripts_zero_reads_none(self):
        code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path,
                                      "--transcripts", "0"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("migrate the export module", stdout)

    def test_invalid_counts_are_usage_errors(self):
        for flag, value in (("--threads", "0"), ("--transcripts", "-1"), ("--max-chars", "10")):
            code, _, _ = run_main(["context", "x", "--ledger", self.ledger_path, flag, value])
            self.assertEqual(code, 2, flag)

    def test_writes_nothing(self):
        before = snapshot(self.tmp.name)
        run_main(["context", "shop", "--ledger", self.ledger_path])
        run_main(["context", "--ledger", self.ledger_path, "--json"])
        self.assertEqual(snapshot(self.tmp.name), before)

    def test_transcript_outside_sessions_source_is_not_opened(self):
        outside = write_jsonl(os.path.join(self.tmp.name, "elsewhere", "s-1.jsonl"),
                              user("must not be printed"))
        self.write_ledger("C:/no/such", transcript=outside)
        code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertEqual(code, 0, err)
        self.assertNotIn("must not be printed", stdout)
        self.assertIn("excerpts unavailable: path outside sessions source", stdout)

    def test_non_jsonl_transcript_path_is_not_opened(self):
        other = os.path.join(self.tmp.name, "projects", "p", "notes.txt")
        with open(other, "w", encoding="utf-8") as fh:
            fh.write('{"type": "user", "message": {"content": "must not be printed"}}\n')
        self.write_ledger("C:/no/such", transcript=other)
        code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertEqual(code, 0, err)
        self.assertNotIn("must not be printed", stdout)
        self.assertIn("path outside sessions source", stdout)

    def test_default_source_is_claude_projects_when_none_recorded(self):
        self.write_ledger("C:/no/such", source=False)
        with mock.patch.object(cli, "default_sessions_source",
                               return_value=os.path.join(self.tmp.name, "projects")):
            code, stdout, _ = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertIn("migrate the export module", stdout)
        code, stdout, _ = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertIn("path outside sessions source", stdout)

    def test_handoff_notes_from_the_project_folder(self):
        folder = os.path.join(self.tmp.name, "shop")
        os.makedirs(os.path.join(folder, "qa"))
        with open(os.path.join(folder, "qa", "AGENT-NEXT-STEPS.md"), "w", encoding="utf-8") as fh:
            fh.write("# Next\n- finish the export client tests\n")
        self.write_ledger(folder.replace("\\", "/"))
        code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertEqual(code, 0, err)
        self.assertIn("### Handoff notes", stdout)
        self.assertIn("AGENT-NEXT-STEPS.md", stdout)
        self.assertIn("- finish the export client tests", stdout)
        code, stdout, _ = run_main(["context", "shop", "--ledger", self.ledger_path, "--json"])
        self.assertEqual(json.loads(stdout)["projects"][0]["handoff"][0]["truncated"], False)

    def test_sessions_index_carries_the_automation_fields(self):
        with open(self.ledger_path, encoding="utf-8") as fh:
            data = json.load(fh)
        index, _ = cli._sessions_index(data, self.ledger_path)
        self.assertLessEqual({"entrypoint", "userMessages", "assistantMessages", "titleSource",
                              "fork", "lastPrompt"}, set(index["s-1"]))

    def test_privacy_line_is_accurate(self):
        _, stdout, _ = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertIn("This command writes nothing", stdout)
        self.assertNotIn("never stored", stdout)

    def test_live_git_of_a_real_repo(self):
        with Sandbox() as sb:
            repo = sb.init("projects/shop")
            sb.commit(repo, "add totals")
            self.write_ledger(repo.replace("\\", "/"))
            code, stdout, err = run_main(["context", "shop", "--ledger", self.ledger_path])
        self.assertEqual(code, 0, err)
        self.assertIn("Branch: main", stdout)
        self.assertIn("add totals", stdout)


class EmitTest(unittest.TestCase):
    def test_unencodable_text_is_replaced_not_raised(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
        with contextlib.redirect_stdout(stream):
            cli._emit("ok \u2713 done")
        stream.flush()
        self.assertEqual(raw.getvalue(), b"ok ? done\n")


if __name__ == "__main__":
    unittest.main()
