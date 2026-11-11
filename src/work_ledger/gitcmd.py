"""Run read-only git commands: argv only, no shell, timeout, sanitized env."""

import os
import subprocess
from dataclasses import dataclass

GIT_EXECUTABLE = "git"
DEFAULT_TIMEOUT = 30

STRIPPED_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES",
)


class GitError(Exception):
    """Base error for git invocation failures (not non-zero exit codes)."""


class GitNotFoundError(GitError):
    pass


class GitTimeoutError(GitError):
    pass


@dataclass(frozen=True)
class GitResult:
    code: int
    stdout: str
    stderr: str


def sanitized_env(base=None):
    env = dict(os.environ if base is None else base)
    for name in STRIPPED_ENV_VARS:
        env.pop(name, None)
    # Never take optional locks (e.g. status refreshing the index) and never prompt.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run_git(path, *args, timeout=DEFAULT_TIMEOUT):
    argv = [GIT_EXECUTABLE, "--no-optional-locks", "-C", str(path), *args]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=sanitized_env(),
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise GitNotFoundError(f"git executable not found: {GIT_EXECUTABLE}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitTimeoutError(f"git timed out after {timeout}s: {' '.join(args)}") from exc
    return GitResult(proc.returncode, proc.stdout, proc.stderr)
