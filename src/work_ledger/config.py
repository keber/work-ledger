"""User settings from a TOML file. Pure, except `load_config`, which reads one file.

The file is `work-ledger.local.toml` at the project root (gitignored), or the path given
by `--config` or `WORK_LEDGER_CONFIG`. `work-ledger.example.toml` is the tracked template.
Every setting resolves as: CLI flag > environment variable > config file > built-in default.
Paths are expanded with `os.path.expanduser`, so `~` works everywhere.
"""

import os
import tomllib
from dataclasses import dataclass

CONFIG_NAME = "work-ledger.local.toml"
CONFIG_ENV = "WORK_LEDGER_CONFIG"
COMPANY_ENV = "WORK_LEDGER_COMPANY_TERMS"  # comma-separated
ROOTS_ENV = "WORK_LEDGER_ROOTS"            # os.pathsep-separated
CLAUDE_ENV = "WORK_LEDGER_CLAUDE"
PUBLISH_ENV = "WORK_LEDGER_PUBLISH_DIR"

# table -> {key: kind}; kind is "terms" (list of str), "paths" (list of paths) or "path".
SCHEMA = {
    "curation": {"company_terms": "terms", "publish_dir": "path", "claude": "path"},
    "inventory": {"roots": "paths"},
}


class ConfigError(Exception):
    """The config file is missing (when named explicitly), unreadable or invalid."""


@dataclass(frozen=True)
class Config:
    """Settings from the file; None means "not set", so the next level applies."""
    company_terms: tuple | None = None
    publish_dir: str | None = None
    claude: str | None = None
    roots: tuple | None = None


def _expand(path):
    return os.path.expanduser(path)


def _value(kind, value, where):
    if kind == "path":
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{where} must be a non-empty string")
        return _expand(value)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(_expand(v) for v in value) if kind == "paths" else tuple(value)


def parse_config(text, source="config"):
    """Config from TOML text. Raises ConfigError on invalid TOML, types or unknown keys."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: invalid TOML: {exc}") from exc
    values = {}
    for table, content in data.items():
        if table not in SCHEMA:
            raise ConfigError(f"{source}: unknown table [{table}]")
        if not isinstance(content, dict):
            raise ConfigError(f"{source}: {table} must be a table")
        for key, value in content.items():
            kind = SCHEMA[table].get(key)
            if kind is None:
                raise ConfigError(f"{source}: unknown key [{table}] {key}")
            values[key] = _value(kind, value, f"{source}: [{table}] {key}")
    return Config(**values)


def config_path(cli_path, environ, project_root, expand=_expand):
    """(path, explicit): `--config`, else $WORK_LEDGER_CONFIG, else the project's local file."""
    explicit = cli_path or environ.get(CONFIG_ENV)
    if explicit:
        return expand(explicit), True
    return os.path.join(project_root, CONFIG_NAME), False


def load_config(path, explicit):
    """Config read from `path`. A missing file is an error only when it was named explicitly."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError as exc:
        if explicit:
            raise ConfigError(f"config file not found: {path}") from exc
        return Config()
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"config file is not UTF-8: {path}") from exc
    return parse_config(text, path)


def _env_list(environ, name, sep):
    items = [i.strip() for i in (environ.get(name) or "").split(sep)]
    return [i for i in items if i] or None


def company_terms(cli_terms, environ, config):
    """Company terms for the public check; () when none is configured anywhere."""
    for terms in (cli_terms, _env_list(environ, COMPANY_ENV, ","), config.company_terms):
        if terms is not None:
            return tuple(t.strip() for t in terms if t and t.strip())
    return ()


def roots(cli_roots, environ, config, default):
    """Inventory roots, each `~`-expanded."""
    for found in (cli_roots, _env_list(environ, ROOTS_ENV, os.pathsep), config.roots):
        if found:
            return [_expand(r) for r in found]
    return list(default)


def setting(cli_value, environ, env_name, config_value):
    """One path setting, `~`-expanded; None when nothing sets it (built-in default applies)."""
    for value in (cli_value, environ.get(env_name), config_value):
        if value:
            return _expand(value)
    return None
