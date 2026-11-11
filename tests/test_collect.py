import json
import os
import shutil
import unittest
from unittest import mock

from tests.gitfixtures import Sandbox, norm
from work_ledger.collect import DEFAULT_IGNORE_UNTRACKED, collect_repo, parse_status
from work_ledger.discover import discover


def only_repo(sb, root="projects", **kwargs):
    refs = discover([sb.path(root)])
    assert len(refs) == 1, refs
    return collect_repo(refs[0], **kwargs)


def branch(repo, name):
    matches = [b for b in repo["branches"] if b["name"] == name]
    assert matches, f"branch {name} not in {[b['name'] for b in repo['branches']]}"
    return matches[0]


def worktree(repo, path):
    matches = [w for w in repo["worktrees"] if w["path"] == norm(path)]
    assert matches, f"{norm(path)} not in {[w['path'] for w in repo['worktrees']]}"
    return matches[0]


def make_remote_clone(sb):
    """Seed a bare origin with main and return a clone under projects/."""
    origin = sb.init_bare("remotes/origin.git")
    seed = sb.init("seed")
    sb.git(seed, "remote", "add", "origin", origin)
    sb.git(seed, "push", "-q", "origin", "main")
    return sb.clone(origin, "projects/app")


class RepoFactsTest(unittest.TestCase):
    def test_repo_level_facts_without_remote(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            repo = only_repo(sb)
        self.assertEqual(repo["path"], norm(repo_path))
        self.assertTrue(repo["commonDir"].endswith("/.git"))
        self.assertEqual(repo["defaultBranch"], "main")
        self.assertFalse(repo["hasRemotes"])
        self.assertIsNone(repo["lastFetch"])
        self.assertIsNone(repo["error"])

    def test_default_branch_from_origin_head(self):
        with Sandbox() as sb:
            make_remote_clone(sb)
            repo = only_repo(sb)
        self.assertEqual(repo["defaultBranch"], "origin/main")
        self.assertTrue(repo["hasRemotes"])

    def test_master_fallback(self):
        with Sandbox() as sb:
            sb.init("projects/app", branch="master")
            repo = only_repo(sb)
        self.assertEqual(repo["defaultBranch"], "master")

    def test_last_fetch_from_fetch_head(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            sb.git(clone, "fetch", "-q", "origin")
            repo = only_repo(sb)
        self.assertRegex(repo["lastFetch"], r"^\d{4}-\d{2}-\d{2}T")


class MainWorktreeTest(unittest.TestCase):
    def test_main_worktree_flagged_and_never_safe(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            repo = only_repo(sb)
        wt = worktree(repo, repo_path)
        self.assertTrue(wt["isMain"])
        self.assertEqual(wt["branch"], "main")
        self.assertTrue(wt["exists"])
        self.assertTrue(wt["merged"])
        self.assertNotEqual(wt["risk"], "safe")
        # No remotes: every commit counts as not on remote, so it is unpushed.
        self.assertEqual(wt["notOnRemote"], 1)
        self.assertEqual(wt["risk"], "unpushed")
        self.assertEqual(wt["lastCommit"]["subject"], "initial")
        self.assertRegex(wt["lastCommit"]["date"], r"^\d{4}-\d{2}-\d{2}T")

    def test_clean_pushed_merged_main_worktree_is_main(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            repo = only_repo(sb)
        wt = worktree(repo, clone)
        self.assertEqual(wt["notOnRemote"], 0)
        self.assertEqual(wt["risk"], "main")

    def test_pushed_unmerged_main_worktree_is_main(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            sb.git(clone, "switch", "-q", "-c", "feature")
            sb.commit(clone, "pushed work")
            sb.git(clone, "push", "-q", "-u", "origin", "feature")
            repo = only_repo(sb)
        wt = worktree(repo, clone)
        self.assertFalse(wt["merged"])
        self.assertEqual(wt["risk"], "main")


class RiskScenariosTest(unittest.TestCase):
    def test_clean_merged_branch_is_safe(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            sb.git(clone, "branch", "done")
            repo = only_repo(sb)
        b = branch(repo, "done")
        self.assertTrue(b["merged"])
        self.assertIsNone(b["upstream"])
        self.assertEqual(b["notOnRemote"], 0)
        self.assertEqual(b["risk"], "safe")
        # Checked-out branches are reported as worktrees, not as branches.
        self.assertNotIn("main", [x["name"] for x in repo["branches"]])

    def test_dirty_worktree_is_modified(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            wt_path = sb.path("projects", "app-wip")
            sb.git(repo_path, "worktree", "add", "-q", "-b", "wip", wt_path)
            sb.write(wt_path, "new.txt")
            sb.write(wt_path, "initial.txt", "changed\n")
            sb.write(wt_path, "staged.txt")
            sb.git(wt_path, "add", "staged.txt")
            repo = only_repo(sb)
        wt = worktree(repo, wt_path)
        self.assertFalse(wt["isMain"])
        self.assertEqual(wt["dirty"],
                         {"staged": 1, "unstaged": 1, "untracked": 1, "ignoredUntracked": 0})
        self.assertEqual(wt["risk"], "modified")

    def test_only_untracked_worktree_is_untracked(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            wt_path = sb.path("projects", "app-notes")
            sb.git(clone, "worktree", "add", "-q", "-b", "notes", wt_path, "origin/main")
            sb.write(wt_path, "notes.txt")
            repo = only_repo(sb)
        wt = worktree(repo, wt_path)
        self.assertEqual(wt["notOnRemote"], 0)
        self.assertEqual(wt["dirty"]["untracked"], 1)
        self.assertEqual(wt["risk"], "untracked")

    def test_default_ignore_prefixes_move_untracked_to_ignored(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            wt_path = sb.path("projects", "app-tools")
            sb.git(clone, "worktree", "add", "-q", "-b", "tools", wt_path, "origin/main")
            for folder in (".atl", ".tmp"):
                os.makedirs(os.path.join(wt_path, folder))
                sb.write(os.path.join(wt_path, folder), "f.txt")
            repo = only_repo(sb)
        wt = worktree(repo, wt_path)
        self.assertEqual(wt["dirty"]["untracked"], 0)
        self.assertEqual(wt["dirty"]["ignoredUntracked"], 2)
        self.assertEqual(wt["risk"], "safe")

    def test_extra_ignore_prefix(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            wt_path = sb.path("projects", "app-ref")
            sb.git(clone, "worktree", "add", "-q", "-b", "ref", wt_path, "origin/main")
            os.makedirs(os.path.join(wt_path, "reference"))
            sb.write(os.path.join(wt_path, "reference"), "doc.txt")
            sb.write(wt_path, "keep.txt")
            prefixes = list(DEFAULT_IGNORE_UNTRACKED) + ["reference/"]
            repo = only_repo(sb, ignore_untracked=prefixes)
        wt = worktree(repo, wt_path)
        self.assertEqual(wt["dirty"]["untracked"], 1)
        self.assertEqual(wt["dirty"]["ignoredUntracked"], 1)
        self.assertEqual(wt["risk"], "untracked")

    def test_no_upstream_unmerged_branch_is_unpushed(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            sb.git(repo_path, "switch", "-q", "-c", "feature")
            sb.commit(repo_path, "feature work")
            sb.git(repo_path, "switch", "-q", "main")
            repo = only_repo(sb)
        b = branch(repo, "feature")
        self.assertFalse(b["merged"])
        self.assertEqual(b["notOnRemote"], 2)  # no remotes: every commit counts
        self.assertEqual(b["risk"], "unpushed")
        self.assertEqual(b["lastCommit"]["subject"], "feature work")

    def test_no_upstream_branch_counts_commits_not_on_any_remote(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            sb.git(clone, "switch", "-q", "-c", "feature")
            sb.commit(clone, "one")
            sb.commit(clone, "two")
            sb.git(clone, "switch", "-q", "main")
            repo = only_repo(sb)
        b = branch(repo, "feature")
        self.assertIsNone(b["upstream"])
        self.assertIsNone(b["ahead"])
        self.assertEqual(b["notOnRemote"], 2)
        self.assertEqual(b["risk"], "unpushed")

    def test_branch_ahead_of_upstream_is_unpushed(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            sb.git(clone, "switch", "-q", "-c", "feature")
            sb.commit(clone, "pushed work")
            sb.git(clone, "push", "-q", "-u", "origin", "feature")
            sb.commit(clone, "local only")
            sb.git(clone, "switch", "-q", "main")
            repo = only_repo(sb)
        b = branch(repo, "feature")
        self.assertEqual(b["upstream"], "origin/feature")
        self.assertEqual((b["ahead"], b["behind"]), (1, 0))
        self.assertEqual(b["notOnRemote"], 1)
        self.assertEqual(b["risk"], "unpushed")

    def test_pushed_unmerged_branch_is_pushed(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            sb.git(clone, "switch", "-q", "-c", "feature")
            sb.commit(clone, "pushed work")
            sb.git(clone, "push", "-q", "-u", "origin", "feature")
            sb.git(clone, "switch", "-q", "main")
            repo = only_repo(sb)
        b = branch(repo, "feature")
        self.assertEqual((b["ahead"], b["behind"]), (0, 0))
        self.assertFalse(b["merged"])
        self.assertEqual(b["notOnRemote"], 0)
        self.assertEqual(b["risk"], "pushed")

    def test_gone_upstream_is_flagged(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            sb.git(clone, "switch", "-q", "-c", "feature")
            sb.commit(clone, "pushed work")
            sb.git(clone, "push", "-q", "-u", "origin", "feature")
            sb.git(clone, "switch", "-q", "main")
            sb.git(clone, "update-ref", "-d", "refs/remotes/origin/feature")
            repo = only_repo(sb)
        b = branch(repo, "feature")
        self.assertTrue(b["upstreamGone"])
        self.assertEqual(b["notOnRemote"], 1)
        self.assertEqual(b["risk"], "unpushed")

    def test_deleted_worktree_folder_is_missing(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            wt_path = sb.path("projects", "app-gone")
            sb.git(repo_path, "worktree", "add", "-q", "-b", "gone", wt_path)
            shutil.rmtree(wt_path)
            repo = only_repo(sb)
        wt = worktree(repo, wt_path)
        self.assertFalse(wt["exists"])
        self.assertTrue(wt["prunable"])
        self.assertEqual(wt["notOnRemote"], 1)  # computed from the shared git dir
        self.assertEqual(wt["risk"], "missing")

    def test_locked_worktree(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            wt_path = sb.path("projects", "app-locked")
            sb.git(repo_path, "worktree", "add", "-q", "--lock", "-b", "locked", wt_path)
            repo = only_repo(sb)
        self.assertTrue(worktree(repo, wt_path)["locked"])

    def test_detached_worktree(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            wt_path = sb.path("projects", "app-detached")
            sb.git(clone, "worktree", "add", "-q", "--detach", wt_path)
            repo = only_repo(sb)
        wt = worktree(repo, wt_path)
        self.assertIsNone(wt["branch"])
        self.assertTrue(wt["detached"])
        self.assertRegex(wt["head"], r"^[0-9a-f]{40}$")
        self.assertEqual(wt["notOnRemote"], 0)
        self.assertEqual(wt["risk"], "safe")

    def test_detached_worktree_with_local_commit_is_unpushed(self):
        with Sandbox() as sb:
            clone = make_remote_clone(sb)
            wt_path = sb.path("projects", "app-detached")
            sb.git(clone, "worktree", "add", "-q", "--detach", wt_path)
            sb.commit(wt_path, "detached work")
            repo = only_repo(sb)
        wt = worktree(repo, wt_path)
        self.assertEqual(wt["notOnRemote"], 1)
        self.assertEqual(wt["risk"], "unpushed")

    def test_no_default_branch_is_unknown_only_when_merge_state_needed(self):
        with Sandbox() as sb:
            origin = sb.init_bare("remotes/origin.git", branch="trunk")
            repo_path = sb.init("projects/app", branch="trunk")
            sb.git(repo_path, "remote", "add", "origin", origin)
            sb.git(repo_path, "push", "-q", "origin", "trunk")
            sb.git(repo_path, "branch", "other")
            sb.git(repo_path, "switch", "-q", "-c", "local")
            sb.commit(repo_path, "local work")
            sb.git(repo_path, "switch", "-q", "trunk")
            repo = only_repo(sb)
        self.assertIsNone(repo["defaultBranch"])
        # Clean and nothing unpushed: merge state is needed and unknown.
        self.assertEqual(worktree(repo, repo_path)["risk"], "unknown")
        self.assertEqual(branch(repo, "other")["risk"], "unknown")
        self.assertIsNone(branch(repo, "other")["merged"])
        # notOnRemote does not need the default branch.
        self.assertEqual(branch(repo, "local")["notOnRemote"], 1)
        self.assertEqual(branch(repo, "local")["risk"], "unpushed")

    def test_repo_level_error_becomes_unknown(self):
        with Sandbox() as sb:
            broken = sb.path("projects", "broken")
            os.makedirs(broken)
            with open(os.path.join(broken, ".git"), "w", encoding="utf-8") as fh:
                fh.write("gitdir: does/not/exist\n")
            repo = only_repo(sb)
        self.assertEqual(repo["risk"], "unknown")
        self.assertTrue(repo["error"])
        self.assertEqual(repo["worktrees"], [])

    def test_repo_risk_is_worst_of_items(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            sb.write(repo_path, "initial.txt", "changed\n")
            sb.git(repo_path, "branch", "done")
            repo = only_repo(sb)
        self.assertEqual(repo["risk"], "modified")

    def test_read_only_no_index_or_ref_changes(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            sb.write(repo_path, "initial.txt", "changed\n")
            git_dir = os.path.join(repo_path, ".git")
            before = {p: os.path.getmtime(os.path.join(git_dir, p))
                      for p in ("index", "HEAD", "config")}
            only_repo(sb)
            after = {p: os.path.getmtime(os.path.join(git_dir, p)) for p in before}
            self.assertEqual(before, after)
            self.assertFalse(os.path.exists(os.path.join(git_dir, "FETCH_HEAD")))


class OwnershipTest(unittest.TestCase):
    def test_own_last_commit(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            sb.git(repo_path, "branch", "mine")
            repo = only_repo(sb)
        self.assertIs(worktree(repo, repo_path)["lastCommit"]["isOwn"], True)
        self.assertIs(branch(repo, "mine")["lastCommit"]["isOwn"], True)

    def test_email_match_is_case_insensitive(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            sb.git(repo_path, "config", "user.email", "TEST@Example.Invalid")
            repo = only_repo(sb)
        self.assertIs(worktree(repo, repo_path)["lastCommit"]["isOwn"], True)

    def test_other_author_is_not_own_and_email_not_stored(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            sb.git(repo_path, "switch", "-q", "-c", "theirs")
            sb.commit(repo_path, "their work", author="Other Person <other.person@corp.invalid>")
            sb.git(repo_path, "switch", "-q", "main")
            repo = only_repo(sb)
        b = branch(repo, "theirs")
        self.assertIs(b["lastCommit"]["isOwn"], False)
        dumped = json.dumps(repo).lower()
        self.assertNotIn("other.person", dumped)
        self.assertNotIn("@", dumped)

    def test_unset_user_email_is_null(self):
        with Sandbox() as sb:
            repo_path = sb.init("projects/app")
            sb.git(repo_path, "branch", "b")
            sb.git(repo_path, "config", "--unset", "user.email")
            sb.write(sb.home, "empty-gitconfig", "")
            env = {"GIT_CONFIG_GLOBAL": os.path.join(sb.home, "empty-gitconfig"),
                   "GIT_CONFIG_NOSYSTEM": "1"}
            with mock.patch.dict(os.environ, env):
                repo = only_repo(sb)
        self.assertIsNone(worktree(repo, repo_path)["lastCommit"]["isOwn"])
        self.assertIsNone(branch(repo, "b")["lastCommit"]["isOwn"])


class ParseStatusTest(unittest.TestCase):
    def test_counts_and_ignore_prefixes(self):
        raw = "\0".join([" M a.txt", "A  b.txt", "?? .atl/", "?? .tmp/x.log",
                         "?? notes.txt", "?? sub/.atl/", "R  new.txt", "old.txt", ""])
        counts = parse_status(raw, [".atl/", ".tmp/"])
        self.assertEqual(counts, {"staged": 2, "unstaged": 1, "untracked": 2,
                                  "ignoredUntracked": 2})

    def test_no_prefixes_counts_all_untracked(self):
        counts = parse_status("?? .atl/\0?? a\0")
        self.assertEqual((counts["untracked"], counts["ignoredUntracked"]), (2, 0))

    def test_prefix_without_slash_is_plain_prefix(self):
        counts = parse_status("?? build.log\0?? builder/\0", ["build"])
        self.assertEqual(counts["ignoredUntracked"], 2)

    def test_backslashes_in_prefix_are_normalized(self):
        counts = parse_status("?? ref/docs/a.txt\0", ["ref\\docs\\"])
        self.assertEqual(counts["ignoredUntracked"], 1)

    def test_default_prefixes(self):
        self.assertEqual(list(DEFAULT_IGNORE_UNTRACKED), [".atl/", ".tmp/"])


if __name__ == "__main__":
    unittest.main()
