import hashlib
import unittest

from tests.threadfixtures import br, fork, inventory, repo, session, wt
from work_ledger.threads_identity import (anchor_path, cwd_path, inventory_items, is_project_scope,
                                          project_id, project_key, resolve_session,
                                          short_default_branch, short_key, split_git_key,
                                          thread_id, worktree_index)

INV = inventory(
    repo("C:/r/app", [wt("C:/r/app", "main", is_main=True),
                      wt("C:/r/app/.wt/feat", "feat/x", risk="unpushed"),
                      wt("C:/r/app-hotfix", detached=True, risk="safe")],
         [br("old", risk="safe"), br("wip", risk="modified")]),
    repo("C:/r/lib", [wt("C:/r/lib", "dev", is_main=True)]),
)


def resolve(s, inv=INV):
    return resolve_session(s, worktree_index(inv))


class ThreadIdTest(unittest.TestCase):
    def test_first_12_hex_of_sha256(self):
        key = "git:C:/r/app#main"
        self.assertEqual(thread_id(key), hashlib.sha256(key.encode("utf-8")).hexdigest()[:12])
        self.assertEqual(thread_id(key), thread_id("git:C:/r/app#main"))
        self.assertNotEqual(thread_id(key), thread_id("git:C:/r/app#dev"))


class AnchorPathTest(unittest.TestCase):
    def test_write_anchor_wins(self):
        self.assertEqual(anchor_path(session("s", anchor="C:/w/a", cwd="C:/c")), "C:/w/a")

    def test_most_frequent_cwd(self):
        s = session("s", cwd="C:/c")
        s["cwds"].append({"path": "C:/other", "count": 1})
        self.assertEqual(anchor_path(s), "C:/c")

    def test_relocated_cwd_beats_cwd(self):
        self.assertEqual(anchor_path(session("s", cwd="C:/c", relocated="C:/moved")), "C:/moved")

    def test_none_without_any_path(self):
        self.assertIsNone(anchor_path(session("s", cwd=None)))


class ResolveTest(unittest.TestCase):
    def test_branch_worktree(self):
        self.assertEqual(resolve(session("s", cwd="C:/r/lib/src")), ("git:C:/r/lib#dev", "git"))

    def test_longest_worktree_prefix_wins(self):
        key, _ = resolve(session("s", anchor="C:/r/app/.wt/feat/src", cwd="C:/elsewhere"))
        self.assertEqual(key, "git:C:/r/app#feat/x")

    def test_prefix_must_end_at_a_path_boundary(self):
        # C:/r/app is not a prefix of C:/r/app-hotfix.
        self.assertEqual(resolve(session("s", cwd="C:/r/app-hotfix/x"))[0],
                         "git:C:/r/app@C:/r/app-hotfix")

    def test_case_insensitive_and_backslashes(self):
        self.assertEqual(resolve(session("s", cwd="c:\\R\\LIB\\src"))[0], "git:C:/r/lib#dev")

    def test_detached_worktree(self):
        self.assertEqual(resolve(session("s", anchor="C:/r/app-hotfix")),
                         ("git:C:/r/app@C:/r/app-hotfix", "git"))

    def test_session_branch_used_when_cwd_in_same_worktree(self):
        # The branch the session worked on, even if the worktree moved on since.
        s = session("s", cwd="C:/r/app", branch="feat/gone")
        self.assertEqual(resolve(s)[0], "git:C:/r/app#feat/gone")

    def test_session_branch_ignored_when_cwd_in_other_repo(self):
        s = session("s", anchor="C:/r/lib", cwd="C:/r/app", branch="main")
        self.assertEqual(resolve(s)[0], "git:C:/r/lib#dev")

    def test_relocated_cwd_resolves(self):
        self.assertEqual(resolve(session("s", cwd="C:/old", relocated="C:/r/lib"))[0],
                         "git:C:/r/lib#dev")

    def test_dir_when_outside_worktrees_with_writes(self):
        self.assertEqual(resolve(session("s", anchor="C:/home/.claude/skills/pdf", cwd="C:/r/app")),
                         ("dir:C:/home/.claude/skills/pdf", "dir"))

    def test_session_when_outside_worktrees_without_writes(self):
        self.assertEqual(resolve(session("abc", cwd="C:/ClaudeSession")), ("session:abc", "session"))
        self.assertEqual(resolve(session("def", cwd=None)), ("session:def", "session"))


class DefaultBranchTest(unittest.TestCase):
    def test_default_branch_without_fork_is_one_thread_per_session(self):
        self.assertEqual(resolve(session("s1", cwd="C:/r/app")),
                         ("git:C:/r/app#main~session:s1", "git"))

    def test_default_branch_fork_family_shares_a_thread(self):
        s = session("c", cwd="C:/r/app/src", fork=fork("f1", ["p"], 4, parent="p"))
        self.assertEqual(resolve(s)[0], "git:C:/r/app#main~family:f1")

    def test_session_branch_decides_default_branch(self):
        s = session("s", cwd="C:/r/app", branch="feat/y")
        self.assertEqual(resolve(s)[0], "git:C:/r/app#feat/y")

    def test_repo_without_default_branch_keeps_branch_key(self):
        r = repo("C:/r/solo", [wt("C:/r/solo", "main", is_main=True)])
        r["defaultBranch"] = None
        self.assertEqual(resolve(session("s", cwd="C:/r/solo"), inventory(r))[0],
                         "git:C:/r/solo#main")

    def test_remote_tracking_default_branch_matches_local_branch(self):
        r = repo("C:/r/qa", [wt("C:/r/qa", "master", is_main=True)])
        r["defaultBranch"] = "origin/master"
        inv = inventory(r)
        self.assertEqual(resolve(session("s", cwd="C:/r/qa", branch="master"), inv)[0],
                         "git:C:/r/qa#master~session:s")
        self.assertEqual(resolve(session("t", cwd="C:/r/qa", branch="feat"), inv)[0],
                         "git:C:/r/qa#feat")

    def test_short_default_branch(self):
        self.assertEqual(short_default_branch({"defaultBranch": "origin/main"}), "main")
        self.assertEqual(short_default_branch({"defaultBranch": "origin/wikiMaster"}),
                         "wikiMaster")
        self.assertEqual(short_default_branch({"defaultBranch": "main"}), "main")
        self.assertIsNone(short_default_branch({"defaultBranch": None}))
        # Remote names from the inventory win over the origin/ fallback.
        self.assertEqual(short_default_branch({"defaultBranch": "upstream/dev",
                                               "remotes": ["upstream"]}), "dev")
        self.assertEqual(short_default_branch({"defaultBranch": "upstream/dev"}),
                         "upstream/dev")
        self.assertEqual(short_default_branch({"defaultBranch": "feature/x",
                                               "remotes": ["origin"]}), "feature/x")

    def test_is_project_scope(self):
        self.assertTrue(is_project_scope("git:C:/r/app#main~session:s1"))
        self.assertTrue(is_project_scope("git:C:/r/app#main~family:f1"))
        self.assertFalse(is_project_scope("git:C:/r/app#feat/x"))
        self.assertFalse(is_project_scope("git:C:/r/app@C:/r/app-hotfix"))
        self.assertFalse(is_project_scope("dir:C:/a~b"))


class GitBashPathTest(unittest.TestCase):
    def test_git_bash_paths_resolve_to_worktrees(self):
        self.assertEqual(resolve(session("s", cwd="/c/r/lib/src"))[0], "git:C:/r/lib#dev")
        self.assertEqual(resolve(session("s", anchor="/c/r/app/.wt/feat", cwd="C:/x"))[0],
                         "git:C:/r/app#feat/x")

    def test_git_bash_dir_anchor_is_normalized(self):
        self.assertEqual(resolve(session("s", anchor="/c/notes/plan")), ("dir:C:/notes/plan", "dir"))
        self.assertEqual(cwd_path(session("s", cwd="/d/x")), "D:/x")


class ProjectKeyTest(unittest.TestCase):
    def test_repo_project_for_any_git_thread(self):
        for key in ("git:C:/r/app#main~session:s", "git:C:/r/app#feat/x",
                    "git:C:/r/app@C:/r/app-hotfix"):
            self.assertEqual(project_key(session("s"), key, "git"), ("repo:C:/r/app", "repo"), key)

    def test_dir_project_for_dir_thread(self):
        self.assertEqual(project_key(session("s", anchor="C:/n"), "dir:C:/n", "dir"),
                         ("dir:C:/n", "dir"))

    def test_session_thread_project_is_its_cwd(self):
        s = session("s", cwd="C:/ClaudeSession")
        self.assertEqual(project_key(s, "session:s", "session"), ("dir:C:/ClaudeSession", "dir"))
        s = session("s", cwd="C:/old", relocated="/c/new")
        self.assertEqual(project_key(s, "session:s", "session"), ("dir:C:/new", "dir"))

    def test_session_without_any_path(self):
        self.assertEqual(project_key(session("s", cwd=None), "session:s", "session"),
                         ("dir:", "dir"))

    def test_project_id_is_sha256_prefix(self):
        key = "repo:C:/r/app"
        self.assertEqual(project_id(key), hashlib.sha256(key.encode("utf-8")).hexdigest()[:12])


class InventoryItemsTest(unittest.TestCase):
    def test_keys_for_worktrees_and_branches(self):
        items = {key: (worktree_path, item.get("risk")) for key, _, _, worktree_path, item
                 in inventory_items(INV)}
        self.assertEqual(items["git:C:/r/app#feat/x"], ("C:/r/app/.wt/feat", "unpushed"))
        self.assertEqual(items["git:C:/r/app@C:/r/app-hotfix"], ("C:/r/app-hotfix", "safe"))
        self.assertEqual(items["git:C:/r/app#wip"], (None, "modified"))
        self.assertEqual(len(items), 6)


class ShortKeyTest(unittest.TestCase):
    def test_short_keys(self):
        self.assertEqual(short_key("git:C:/r/app#feat/x"), "git:app#feat/x")
        self.assertEqual(short_key("git:C:/r/app@C:/r/app-hotfix"), "git:app@app-hotfix")
        self.assertEqual(short_key("dir:C:/home/.claude/skills/pdf"), "dir:pdf")
        self.assertEqual(short_key("session:0123456789abcdef"), "session:01234567")
        self.assertEqual(short_key("git:C:/r/app#main~family:0123456789abcdef"),
                         "git:app#main~family:01234567")
        self.assertEqual(short_key("git:C:/r/app#main~session:abcdef0123456"),
                         "git:app#main~session:abcdef01")

    def test_split_git_key_drops_the_thread_suffix(self):
        self.assertEqual(split_git_key("git:C:/r/app#main~family:f1"), ("C:/r/app", "main", None))


if __name__ == "__main__":
    unittest.main()
