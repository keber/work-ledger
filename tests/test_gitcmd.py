import os
import tempfile
import unittest
from unittest import mock

from work_ledger import gitcmd


class SanitizedEnvTest(unittest.TestCase):
    def test_removes_repo_overriding_vars(self):
        dirty = {name: "x" for name in gitcmd.STRIPPED_ENV_VARS}
        dirty["PATH"] = os.environ.get("PATH", "")
        dirty["KEEP_ME"] = "1"
        env = gitcmd.sanitized_env(dirty)
        for name in gitcmd.STRIPPED_ENV_VARS:
            self.assertNotIn(name, env)
        self.assertEqual(env["KEEP_ME"], "1")
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_spec_vars_are_stripped(self):
        expected = {
            "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
            "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
        }
        self.assertTrue(expected.issubset(set(gitcmd.STRIPPED_ENV_VARS)))


class RunGitTest(unittest.TestCase):
    def test_returns_code_stdout_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = gitcmd.run_git(tmp, "rev-parse", "--is-inside-work-tree")
        self.assertNotEqual(result.code, 0)
        self.assertIn("not a git repository", result.stderr)

    def test_success(self):
        result = gitcmd.run_git(".", "--version")
        self.assertEqual(result.code, 0)
        self.assertTrue(result.stdout.startswith("git version"))

    def test_ignores_inherited_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GIT_DIR": os.path.join(tmp, "nope")}):
                result = gitcmd.run_git(tmp, "rev-parse", "--is-inside-work-tree")
        self.assertIn("not a git repository", result.stderr)

    def test_missing_git_raises(self):
        with mock.patch.object(gitcmd, "GIT_EXECUTABLE", "git-does-not-exist-xyz"):
            with self.assertRaises(gitcmd.GitNotFoundError):
                gitcmd.run_git(".", "--version")

    def test_timeout_raises(self):
        with mock.patch.object(gitcmd.subprocess, "run",
                               side_effect=gitcmd.subprocess.TimeoutExpired("git", 1)):
            with self.assertRaises(gitcmd.GitTimeoutError):
                gitcmd.run_git(".", "--version", timeout=1)

    def test_errors_share_base_type(self):
        self.assertTrue(issubclass(gitcmd.GitTimeoutError, gitcmd.GitError))
        self.assertTrue(issubclass(gitcmd.GitNotFoundError, gitcmd.GitError))


if __name__ == "__main__":
    unittest.main()
