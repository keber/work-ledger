"""Helpers that build real git repos in temp dirs, isolated from user config."""

import os
import subprocess
import tempfile


def _env(home):
    env = dict(os.environ)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(name, None)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.path.join(home, "gitconfig")
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


class Sandbox:
    """A temp directory with git helpers. Use as a context manager."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.home = os.path.join(self.root, "_home")
        os.makedirs(self.home)
        with open(os.path.join(self.home, "gitconfig"), "w", encoding="utf-8") as fh:
            fh.write(
                "[user]\n\tname = Test\n\temail = test@example.invalid\n"
                "[init]\n\tdefaultBranch = main\n"
                "[commit]\n\tgpgsign = false\n"
                "[core]\n\tautocrlf = false\n"
            )
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def git(self, cwd, *args):
        proc = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True, text=True, env=_env(self.home), check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout.strip()

    def init(self, rel, branch="main"):
        repo = self.path(rel)
        os.makedirs(repo, exist_ok=True)
        self.git(repo, "init", "-q", f"--initial-branch={branch}")
        self.git(repo, "config", "user.name", "Test")
        self.git(repo, "config", "user.email", "test@example.invalid")
        self.commit(repo, "initial")
        return repo

    def init_bare(self, rel, branch="main"):
        repo = self.path(rel)
        os.makedirs(repo, exist_ok=True)
        self.git(repo, "init", "-q", "--bare", f"--initial-branch={branch}")
        return repo

    def clone(self, src, rel):
        dest = self.path(rel)
        self.git(self.root, "clone", "-q", src, dest)
        self.git(dest, "config", "user.name", "Test")
        self.git(dest, "config", "user.email", "test@example.invalid")
        return dest

    def commit(self, repo, message, filename=None, author=None):
        name = filename or f"{message.replace(' ', '_')}.txt"
        with open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
            fh.write(message + "\n")
        self.git(repo, "add", name)
        extra = [f"--author={author}"] if author else []
        self.git(repo, "commit", "-q", "-m", message, *extra)

    def write(self, repo, name, content="x\n"):
        with open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
            fh.write(content)


def norm(path):
    return os.path.realpath(path).replace("\\", "/")
