import os
import unittest

from tests.gitfixtures import Sandbox, norm
from work_ledger.discover import discover


class DiscoverTest(unittest.TestCase):
    def test_finds_repos_up_to_depth_two(self):
        with Sandbox() as sb:
            sb.init("projects/a")
            sb.init("projects/group/b")
            sb.init("projects/group/deep/c")  # depth 3: not found
            os.makedirs(sb.path("projects", "plain"))
            found = discover([sb.path("projects")])
        paths = sorted(r.main_path for r in found)
        self.assertEqual(paths, sorted([norm(sb.path("projects/a")),
                                        norm(sb.path("projects/group/b"))]))

    def test_dedupes_repo_and_linked_worktree(self):
        with Sandbox() as sb:
            repo = sb.init("projects/app")
            sb.git(repo, "worktree", "add", "-q", "-b", "feat", sb.path("projects", "app-feat"))
            found = discover([sb.path("projects")])
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].main_path, norm(repo))
            self.assertTrue(found[0].common_dir.endswith("/.git"))

    def test_only_linked_worktree_under_root_reports_main_repo(self):
        with Sandbox() as sb:
            repo = sb.init("elsewhere/app")
            sb.git(repo, "worktree", "add", "-q", "-b", "feat", sb.path("projects", "app-feat"))
            found = discover([sb.path("projects")])
        self.assertEqual([r.main_path for r in found], [norm(repo)])

    def test_same_repo_from_two_roots_once(self):
        with Sandbox() as sb:
            sb.init("projects/app")
            found = discover([sb.path("projects"), sb.path("projects")])
        self.assertEqual(len(found), 1)

    def test_missing_root_is_skipped(self):
        with Sandbox() as sb:
            self.assertEqual(discover([sb.path("nope")]), [])

    def test_broken_git_entry_reported_as_error(self):
        with Sandbox() as sb:
            broken = sb.path("projects", "broken")
            os.makedirs(broken)
            with open(os.path.join(broken, ".git"), "w", encoding="utf-8") as fh:
                fh.write("gitdir: does/not/exist\n")
            found = discover([sb.path("projects")])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].main_path, norm(broken))
        self.assertTrue(found[0].error)


if __name__ == "__main__":
    unittest.main()
