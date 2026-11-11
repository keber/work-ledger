import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests.gitfixtures import Sandbox, norm
from tests.sessionfixtures import tool, user, write_jsonl
from tests.threadfixtures import inventory, overrides, repo, session, sessions_report, wt
from work_ledger import cli

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DEFAULT_OVERRIDES = cli.default_overrides


def run_main(argv):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, err.getvalue()


class DefaultsTest(unittest.TestCase):
    def test_default_roots(self):
        home = os.path.expanduser("~")
        self.assertEqual(cli.default_roots(),
                         [os.path.join(home, "Proyectos"), os.path.join(home, "source", "repos")])

    def test_default_out_is_project_out(self):
        self.assertEqual(os.path.normcase(cli.default_out()),
                         os.path.normcase(os.path.join(PROJECT, "out")))


class InventoryCommandTest(unittest.TestCase):
    def test_writes_reports_for_roots(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            out = sb.path("out")
            code, _ = run_main(["inventory", "--root", sb.path("projects"), "--out", out])
            self.assertEqual(code, 0)
            with open(os.path.join(out, "git-inventory.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertTrue(os.path.isfile(os.path.join(out, "git-inventory.md")))
        self.assertEqual(data["schemaVersion"], 2)
        self.assertEqual(data["ignoreUntracked"], [".atl/", ".tmp/"])
        self.assertEqual([r["path"] for r in data["repos"]], [norm(repo_path)])
        self.assertEqual(data["roots"], [norm(sb.path("projects"))])

    def test_repeatable_root(self):
        with Sandbox() as sb:
            sb.init("one/a")
            sb.init("two/b")
            out = sb.path("out")
            code, _ = run_main(["inventory", "--root", sb.path("one"),
                                "--root", sb.path("two"), "--out", out])
            with open(os.path.join(out, "git-inventory.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertEqual(code, 0)
        self.assertEqual(len(data["repos"]), 2)

    def test_repo_failure_does_not_crash_run(self):
        with Sandbox() as sb:
            sb.init("projects/a")
            sb.init("projects/b")
            out = sb.path("out")
            real = cli.collect_repo

            def flaky(ref, *args, **kwargs):
                if ref.main_path.endswith("/a"):
                    raise RuntimeError("unexpected")
                return real(ref, *args, **kwargs)

            with mock.patch.object(cli, "collect_repo", side_effect=flaky):
                code, _ = run_main(["inventory", "--root", sb.path("projects"), "--out", out])
            with open(os.path.join(out, "git-inventory.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertEqual(code, 0)
        by_path = {r["path"].rsplit("/", 1)[-1]: r for r in data["repos"]}
        self.assertEqual(by_path["a"]["risk"], "unknown")
        self.assertIn("unexpected", by_path["a"]["error"])
        self.assertIsNone(by_path["b"]["error"])

    def test_ignore_untracked_is_repeatable_and_extends_defaults(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            for folder in (".atl", "ref", "scratch"):
                os.makedirs(os.path.join(repo_path, folder))
                sb.write(os.path.join(repo_path, folder), "f.txt")
            sb.write(repo_path, "keep.txt")
            out = sb.path("out")
            code, _ = run_main(["inventory", "--root", sb.path("projects"), "--out", out,
                                "--ignore-untracked", "ref/", "--ignore-untracked", "scratch/"])
            with open(os.path.join(out, "git-inventory.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertEqual(code, 0)
        self.assertEqual(data["ignoreUntracked"], [".atl/", ".tmp/", "ref/", "scratch/"])
        dirty = data["repos"][0]["worktrees"][0]["dirty"]
        self.assertEqual((dirty["untracked"], dirty["ignoredUntracked"]), (1, 3))

    def test_missing_explicit_root_is_invalid_argument(self):
        with Sandbox() as sb:
            code, err = run_main(["inventory", "--root", sb.path("nope"), "--out", sb.path("out")])
        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    def test_missing_default_roots_are_skipped(self):
        with Sandbox() as sb:
            with mock.patch.object(cli, "default_roots", return_value=[sb.path("absent")]):
                code, _ = run_main(["inventory", "--out", sb.path("out")])
        self.assertEqual(code, 0)

    def test_roots_from_config_file(self):
        with Sandbox() as sb:
            config = sb.path("wl.toml")
            with open(config, "w", encoding="utf-8") as fh:
                fh.write(f"[inventory]\nroots = ['{norm(sb.root)}']\n")
            with mock.patch.object(cli, "inventory", return_value=(("j", "m"), {
                    "summary": {"repos": 0, "risks": {}}})) as spy:
                code, err = run_main(["inventory", "--config", config, "--out", sb.path("o")])
        self.assertEqual(code, 0, err)
        self.assertEqual(spy.call_args.args[0], [norm(sb.root)])

    def test_root_flag_expands_the_home_dir(self):
        with Sandbox() as sb:
            home = lambda p: p.replace("~", sb.root, 1) if p.startswith("~") else p  # noqa: E731
            with mock.patch("os.path.expanduser", side_effect=home), \
                    mock.patch.object(cli, "inventory", return_value=(("j", "m"), {
                        "summary": {"repos": 0, "risks": {}}})) as spy:
                code, err = run_main(["inventory", "--root", "~", "--out", sb.path("o")])
        self.assertEqual(code, 0, err)
        self.assertEqual(spy.call_args.args[0], [sb.root])

    def test_unwritable_output_exits_1(self):
        with Sandbox() as sb:
            blocker = sb.path("file")
            sb.write(sb.root, "file")
            code, err = run_main(["inventory", "--root", sb.root, "--out", blocker])
        self.assertEqual(code, 1)
        self.assertIn("cannot write", err)

    def test_no_command_is_invalid(self):
        code, _ = run_main([])
        self.assertEqual(code, 2)


class SessionsCommandTest(unittest.TestCase):
    def test_writes_reports_and_cache(self):
        with Sandbox() as sb:
            source = sb.path("projects")
            write_jsonl(os.path.join(source, "proj", "s1.jsonl"),
                        user(ts="2026-11-01T10:00:00Z"),
                        tool("Bash", {"command": "git push"}, ts="2026-11-01T10:01:00Z"))
            out = sb.path("out")
            code, _ = run_main(["sessions", "--source", source, "--out", out])
            with open(os.path.join(out, "sessions.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertTrue(os.path.isfile(os.path.join(out, "sessions.md")))
            self.assertTrue(os.path.isfile(os.path.join(out, ".cache", "sessions-cache.json")))
            code_cached, _ = run_main(["sessions", "--source", source, "--out", out])
            with open(os.path.join(out, "sessions.json"), encoding="utf-8") as fh:
                cached = json.load(fh)
            code_full, _ = run_main(["sessions", "--source", source, "--out", out, "--full"])
            with open(os.path.join(out, "sessions.json"), encoding="utf-8") as fh:
                full = json.load(fh)
        self.assertEqual((code, code_cached, code_full), (0, 0, 0))
        self.assertEqual(data["schemaVersion"], 3)
        self.assertEqual(data["sourceRoot"], norm(source))
        self.assertEqual(data["sessions"][0]["gitActions"]["push"]["count"], 1)
        self.assertEqual((data["stats"]["parsed"], data["stats"]["cached"]), (1, 0))
        self.assertEqual((cached["stats"]["parsed"], cached["stats"]["cached"]), (0, 1))
        self.assertEqual((full["stats"]["parsed"], full["stats"]["cached"]), (1, 0))

    def test_default_source_is_claude_projects(self):
        self.assertEqual(os.path.normcase(cli.default_sessions_source()),
                         os.path.normcase(os.path.join(os.path.expanduser("~"), ".claude", "projects")))

    def test_missing_explicit_source_is_invalid_argument(self):
        with Sandbox() as sb:
            code, err = run_main(["sessions", "--source", sb.path("nope"), "--out", sb.path("out")])
        self.assertEqual(code, 2)
        self.assertIn("nope", err)

    def test_missing_default_source_is_empty_run(self):
        with Sandbox() as sb:
            with mock.patch.object(cli, "default_sessions_source", return_value=sb.path("absent")):
                code, _ = run_main(["sessions", "--out", sb.path("out")])
        self.assertEqual(code, 0)

    def test_unwritable_output_exits_1(self):
        with Sandbox() as sb:
            sb.write(sb.root, "file")
            os.makedirs(sb.path("projects"))
            code, err = run_main(["sessions", "--source", sb.path("projects"),
                                  "--out", sb.path("file")])
        self.assertEqual(code, 1)
        self.assertIn("cannot write", err)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


class ThreadsCommandTest(unittest.TestCase):
    def setUp(self):
        # Never read the user's real overrides.json at the project root.
        absent = os.path.join(PROJECT, "tests", "no-such-dir", "overrides.json")
        patcher = mock.patch.object(cli, "default_overrides", return_value=absent)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_overrides_is_project_root(self):
        self.assertEqual(os.path.normcase(REAL_DEFAULT_OVERRIDES()),
                         os.path.normcase(os.path.join(PROJECT, "overrides.json")))

    def inputs(self, sb, sessions_version=3):
        out = sb.path("out")
        write_json(os.path.join(out, "git-inventory.json"),
                   inventory(repo("C:/r/app", [wt("C:/r/app", "main", is_main=True)])))
        write_json(os.path.join(out, "sessions.json"),
                   sessions_report(session("s1", cwd="C:/r/app"), session("s2", anchor="C:/n"),
                                   version=sessions_version))
        return out

    def test_defaults_read_from_out_dir_and_write_ledger(self):
        with Sandbox() as sb:
            out = self.inputs(sb)
            code, err = run_main(["threads", "--out", out,
                                  "--overrides", write_json(sb.path("o.json"), overrides())])
            with open(os.path.join(out, "ledger.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertTrue(os.path.isfile(os.path.join(out, "ledger.md")))
        self.assertEqual(code, 0, err)
        self.assertEqual(data["schemaVersion"], 2)
        self.assertEqual(sorted(t["key"] for t in data["threads"]),
                         ["dir:C:/n", "git:C:/r/app#main~session:s1"])
        self.assertEqual(sorted(p["key"] for p in data["projects"]), ["dir:C:/n", "repo:C:/r/app"])
        self.assertTrue(data["inputs"]["overrides"]["present"])

    def test_explicit_input_paths(self):
        with Sandbox() as sb:
            src = self.inputs(sb)
            out = sb.path("elsewhere")
            code, _ = run_main(["threads", "--inventory", os.path.join(src, "git-inventory.json"),
                                "--sessions", os.path.join(src, "sessions.json"), "--out", out])
            self.assertTrue(os.path.isfile(os.path.join(out, "ledger.json")))
        self.assertEqual(code, 0)

    def test_sessions_schema_2_still_accepted(self):
        with Sandbox() as sb:
            code, _ = run_main(["threads", "--out", self.inputs(sb, sessions_version=2)])
        self.assertEqual(code, 0)

    def test_unknown_schema_version_exits_1_with_message(self):
        with Sandbox() as sb:
            code, err = run_main(["threads", "--out", self.inputs(sb, sessions_version=7)])
        self.assertEqual(code, 1)
        self.assertIn("schemaVersion 7", err)

    def test_missing_default_input_exits_1(self):
        with Sandbox() as sb:
            code, err = run_main(["threads", "--out", sb.path("empty")])
        self.assertEqual(code, 1)
        self.assertIn("git-inventory.json", err)

    def test_missing_explicit_path_is_invalid_argument(self):
        with Sandbox() as sb:
            out = self.inputs(sb)
            code, err = run_main(["threads", "--out", out, "--overrides", sb.path("nope.json")])
        self.assertEqual(code, 2)
        self.assertIn("nope.json", err)

    def test_warnings_go_to_stderr(self):
        with Sandbox() as sb:
            out = self.inputs(sb)
            ovr = write_json(sb.path("o.json"), overrides(merge=[{"into": "x", "from": ["y"]}]))
            code, err = run_main(["threads", "--out", out, "--overrides", ovr])
        self.assertEqual(code, 0)
        self.assertIn("warning:", err)


class RefreshCommandTest(unittest.TestCase):
    def runners(self, codes):
        calls = []

        def make(name):
            def run(argv):
                calls.append(argv)
                return codes[name]
            return run
        return calls, [(name, make(name)) for name in ("inventory", "sessions", "threads")]

    def test_runs_steps_in_order_passing_out(self):
        calls, steps = self.runners({"inventory": 0, "sessions": 0, "threads": 0})
        self.assertEqual(cli.refresh("D:/o", steps=steps), 0)
        self.assertEqual(calls, [["inventory", "--out", "D:/o"], ["sessions", "--out", "D:/o"],
                                 ["threads", "--out", "D:/o"]])

    def test_default_arguments_without_out(self):
        calls, steps = self.runners({"inventory": 0, "sessions": 0, "threads": 0})
        cli.refresh(None, steps=steps)
        self.assertEqual(calls, [["inventory"], ["sessions"], ["threads"]])

    def test_passes_an_explicit_config_to_every_step(self):
        calls, steps = self.runners({"inventory": 0, "sessions": 0, "threads": 0})
        cli.refresh("D:/o", steps=steps, config="D:/c.toml")
        self.assertEqual(calls[0], ["inventory", "--out", "D:/o", "--config", "D:/c.toml"])

    def test_stops_at_first_failure_with_its_code(self):
        calls, steps = self.runners({"inventory": 0, "sessions": 3, "threads": 0})
        self.assertEqual(cli.refresh("D:/o", steps=steps), 3)
        self.assertEqual([c[0] for c in calls], ["inventory", "sessions"])

    def test_argument_error_in_a_step_is_its_exit_code(self):
        def boom(argv):
            raise SystemExit(2)
        self.assertEqual(cli.refresh(None, steps=[("inventory", boom)]), 2)

    def test_cli_dispatches_refresh(self):
        with mock.patch.object(cli, "refresh", return_value=5) as spy:
            code, _ = run_main(["refresh", "--out", "D:/o"])
        self.assertEqual(code, 5)
        spy.assert_called_once_with("D:/o", config=None)


class ModuleEntryPointTest(unittest.TestCase):
    def test_python_dash_m_help(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(PROJECT, "src"))
        proc = subprocess.run([sys.executable, "-m", "work_ledger", "inventory", "--help"],
                              capture_output=True, text=True, env=env, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--root", proc.stdout)
        self.assertIn("--ignore-untracked", proc.stdout)


if __name__ == "__main__":
    unittest.main()
