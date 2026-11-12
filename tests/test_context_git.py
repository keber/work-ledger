import os
import unittest

from tests.gitfixtures import Sandbox
from work_ledger import context_git
from work_ledger.context_git import READ_ONLY_COMMANDS, live_git
from work_ledger.gitcmd import GitTimeoutError, run_git


def make_clone(sb):
    origin = sb.init_bare("remotes/origin.git")
    seed = sb.init("seed")
    sb.git(seed, "remote", "add", "origin", origin)
    sb.git(seed, "push", "-q", "origin", "main")
    return sb.clone(origin, "projects/app")


class LiveGitTest(unittest.TestCase):
    def test_missing_path(self):
        state = live_git("C:/definitely/not/here/xyz")
        self.assertEqual(state["status"], "missing")

    def test_none_path(self):
        self.assertEqual(live_git(None)["status"], "missing")

    def test_not_a_repo(self):
        with Sandbox() as sb:
            folder = sb.path("plain")
            os.makedirs(folder)
            state = live_git(folder)
        self.assertEqual(state["status"], "not-a-repo")

    def test_repo_state(self):
        with Sandbox() as sb:
            app = make_clone(sb)
            sb.commit(app, "local only one")
            sb.commit(app, "local only two")
            sb.git(app, "checkout", "-q", "-b", "feat/x")
            sb.commit(app, "feature work")
            sb.git(app, "checkout", "-q", "-b", "merged-already", "origin/main")
            sb.git(app, "checkout", "-q", "main")
            sb.write(app, "new.txt")
            sb.write(app, "initial.txt", "changed\n")
            state = live_git(app)
        self.assertEqual(state["status"], "ok", state)
        self.assertEqual(state["branch"], "main")
        self.assertEqual(state["defaultBranch"], "origin/main")
        self.assertEqual(state["dirty"]["untracked"], 1)
        self.assertEqual(state["dirty"]["unstaged"], 1)
        self.assertEqual(state["notOnRemote"], 3)  # two on main plus one on feat/x
        self.assertEqual(state["headNotOnRemote"], 2)
        subjects = [c["subject"] for c in state["recentCommits"]]
        self.assertEqual(subjects[:2], ["local only two", "local only one"])
        self.assertTrue(state["recentCommits"][0]["date"])
        names = {b["name"]: b for b in state["unmergedBranches"]}
        self.assertEqual(set(names), {"feat/x", "main"})
        self.assertEqual(names["feat/x"]["ahead"], 3)
        self.assertEqual(names["feat/x"]["lastCommit"]["subject"], "feature work")
        self.assertTrue(names["main"]["current"])
        self.assertNotIn("email", repr(state).lower())

    def test_recent_commit_limit(self):
        with Sandbox() as sb:
            app = sb.init("projects/app")
            for i in range(5):
                sb.commit(app, f"c{i}")
            state = live_git(app, recent=3)
        self.assertEqual([c["subject"] for c in state["recentCommits"]], ["c4", "c3", "c2"])
        self.assertEqual(state["defaultBranch"], "main")
        self.assertEqual(state["unmergedBranches"], [])

    def test_detached_head(self):
        with Sandbox() as sb:
            app = sb.init("projects/app")
            sb.commit(app, "second")
            sb.git(app, "checkout", "-q", "--detach", "HEAD~1")
            state = live_git(app)
        self.assertEqual(state["status"], "ok")
        self.assertIsNone(state["branch"])

    def test_only_read_only_git_commands(self):
        calls = []

        def spy(path, *args, **kw):
            calls.append(args[0])
            return run_git(path, *args, **kw)

        with Sandbox() as sb:
            app = make_clone(sb)
            sb.git(app, "checkout", "-q", "-b", "feat/y")
            sb.commit(app, "y")
            live_git(app, run=spy)
        self.assertTrue(calls)
        self.assertLessEqual(set(calls), set(READ_ONLY_COMMANDS))
        self.assertNotIn("fetch", READ_ONLY_COMMANDS)

    def test_git_failure_is_reported(self):
        def boom(path, *args, **kw):
            raise GitTimeoutError("git timed out")

        with Sandbox() as sb:
            folder = sb.path("plain")
            os.makedirs(folder)
            state = live_git(folder, run=boom)
        self.assertEqual(state["status"], "error")
        self.assertIn("timed out", state["error"])

    def test_branch_listing_is_capped(self):
        with Sandbox() as sb:
            app = sb.init("projects/app")
            for i in range(4):
                sb.git(app, "checkout", "-q", "-b", f"b{i}", "main")
                sb.commit(app, f"w{i}")
            sb.git(app, "checkout", "-q", "main")
            state = live_git(app, branch_limit=2)
        self.assertEqual(len(state["unmergedBranches"]), 2)
        self.assertEqual(state["moreUnmergedBranches"], 2)


class ModuleTest(unittest.TestCase):
    def test_uses_shared_git_runner(self):
        self.assertIs(context_git.run_git, run_git)


if __name__ == "__main__":
    unittest.main()
