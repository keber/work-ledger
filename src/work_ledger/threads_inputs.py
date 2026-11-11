"""Load and validate the builder inputs. The only file reads of the thread builder."""

import json
import os

INVENTORY_VERSIONS = (2,)
SESSIONS_VERSIONS = (2, 3)


class InputError(Exception):
    """An input file is missing, unreadable or has an unsupported shape or version."""


def check_schema(data, name, accepted):
    if not isinstance(data, dict):
        raise InputError(f"{name}: expected a JSON object")
    version = data.get("schemaVersion")
    if version not in accepted:
        supported = ", ".join(str(v) for v in accepted)
        raise InputError(f"{name}: unsupported schemaVersion {version} (supported: {supported})")
    return data


def load_json(path, name):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise InputError(f"{name}: file not found: {path}") from None
    except ValueError as exc:
        raise InputError(f"{name}: not valid JSON: {path} ({exc})") from None
    except OSError as exc:
        raise InputError(f"{name}: cannot read {path}: {exc}") from None


def load_inputs(inventory_path, sessions_path, overrides_path):
    """(inventory, sessions report, overrides or None). Overrides are optional."""
    inventory = check_schema(load_json(inventory_path, "inventory"), "inventory",
                             INVENTORY_VERSIONS)
    sessions = check_schema(load_json(sessions_path, "sessions"), "sessions", SESSIONS_VERSIONS)
    overrides = None
    if overrides_path and os.path.exists(overrides_path):
        overrides = load_json(overrides_path, "overrides")
    return inventory, sessions, overrides
