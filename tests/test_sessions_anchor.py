import os
import tempfile
import unittest

from work_ledger.sessions_anchor import AnchorResolver, default_temp_root, is_temp_path


def never_temp(path):
    return False


def posix(path):
    return os.path.realpath(path).replace("\\", "/")


class RootTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = posix(self._tmp.name)
        self.claude = self.root + "/home/.claude"
        os.makedirs(self.root + "/repo/.git")
        os.makedirs(self.root + "/repo/src/deep")
        os.makedirs(self.root + "/wt")
        with open(self.root + "/wt/.git", "w", encoding="utf-8") as fh:
            fh.write("gitdir: elsewhere\n")
        os.makedirs(self.claude + "/skills/latex-pdf")
        self.resolver = AnchorResolver(self.claude)

    def tearDown(self):
        self._tmp.cleanup()

    def test_nearest_git_ancestor_dir(self):
        self.assertEqual(self.resolver.root(self.root + "/repo/src/deep/a.py"), self.root + "/repo")

    def test_git_file_counts_as_repo(self):
        self.assertEqual(self.resolver.root(self.root + "/wt/x/y.txt"), self.root + "/wt")

    def test_path_need_not_exist(self):
        self.assertEqual(self.resolver.root(self.root + "/repo/gone/later.py"), self.root + "/repo")

    def test_claude_home_two_components(self):
        self.assertEqual(self.resolver.root(self.claude + "/skills/latex-pdf/refs/SKILL.md"),
                         self.claude + "/skills/latex-pdf")

    def test_claude_home_shallow_paths(self):
        self.assertEqual(self.resolver.root(self.claude + "/skills/a.md"), self.claude + "/skills")
        self.assertEqual(self.resolver.root(self.claude + "/CLAUDE.md"), self.claude)

    @unittest.skipUnless(os.name == "nt", "case-insensitive paths are a Windows rule")
    def test_claude_home_match_ignores_case_and_slashes(self):
        path = (self.claude.upper() + "/skills/latex-pdf/x.md").replace("/", "\\")
        path = path.replace("SKILLS\\LATEX-PDF", "skills\\latex-pdf")
        self.assertEqual(self.resolver.root(path), self.claude + "/skills/latex-pdf")

    def test_parent_dir_fallback(self):
        self.assertEqual(self.resolver.root(self.root + "/loose/notes/n.md"), self.root + "/loose/notes")

    def test_git_ancestor_checks_are_memoized(self):
        calls = []

        def spy(path):
            calls.append(path)
            return os.path.lexists(path)

        resolver = AnchorResolver(self.claude, lexists=spy)
        resolver.root(self.root + "/repo/src/deep/a.py")
        first = len(calls)
        resolver.root(self.root + "/repo/src/deep/b.py")
        self.assertEqual(len(calls), first)


class WriteAnchorTest(unittest.TestCase):
    def test_none_without_writes(self):
        self.assertIsNone(AnchorResolver("/nowhere/.claude").write_anchor([]))

    def test_root_with_most_writes_and_share(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = posix(tmp)
            os.makedirs(root + "/a/.git")
            writes = [{"path": root + "/a/x.py", "count": 2}, {"path": root + "/a/sub/y.py", "count": 1},
                      {"path": root + "/b/z.md", "count": 1}]
            anchor = AnchorResolver(root + "/.claude", is_temp=never_temp).write_anchor(writes)
        self.assertEqual(anchor, {"path": root + "/a", "share": 0.75})

    def test_tie_is_deterministic(self):
        writes = [{"path": "/q/b/1", "count": 1}, {"path": "/q/a/1", "count": 1}]
        anchor = AnchorResolver("/nowhere/.claude", lexists=lambda p: False).write_anchor(writes)
        self.assertEqual(anchor, {"path": "/q/a", "share": 0.5})

    def test_temp_writes_are_excluded(self):
        writes = [{"path": "/tmp/x/scratch.py", "count": 5}, {"path": "/q/a/1", "count": 1}]
        resolver = AnchorResolver("/nowhere/.claude", lexists=lambda p: False,
                                  is_temp=lambda p: p.startswith("/tmp/"))
        self.assertEqual(resolver.write_anchor(writes), {"path": "/q/a", "share": 1.0})

    def test_only_temp_writes_give_no_anchor(self):
        resolver = AnchorResolver("/nowhere/.claude", lexists=lambda p: False,
                                  is_temp=lambda p: True)
        self.assertIsNone(resolver.write_anchor([{"path": "/tmp/a", "count": 2}]))

    def test_default_excludes_system_temp_dir(self):
        writes = [{"path": default_temp_root() + "/x/y.py", "count": 1}]
        self.assertIsNone(AnchorResolver("/nowhere/.claude").write_anchor(writes))


class IsTempPathTest(unittest.TestCase):
    def test_under_temp_root_ignoring_case_and_slashes(self):
        self.assertTrue(is_temp_path(r"c:\tmp\Build\a.py", "C:/TMP"))
        self.assertTrue(is_temp_path("C:/TMP", "C:/TMP"))

    def test_sibling_prefix_is_not_temp(self):
        self.assertFalse(is_temp_path("C:/tmpfiles/a.py", "C:/tmp"))

    def test_appdata_local_temp_matches_short_names(self):
        self.assertTrue(is_temp_path("C:/Users/JOHNDO~1/AppData/Local/Temp/x/a.py",
                                     "C:/Users/john.doe/AppData/Local/Temp"))
        self.assertTrue(is_temp_path("C:/Users/someone/appdata/local/TEMP/a.py", None))

    def test_regular_path_is_not_temp(self):
        self.assertFalse(is_temp_path("C:/Users/me/Proyectos/app/a.py", "C:/tmp"))
        self.assertFalse(is_temp_path("C:/Users/me/AppData/Local/Templates/a.py", None))


if __name__ == "__main__":
    unittest.main()
