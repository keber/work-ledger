"""JSON schema of the model output and its validation in Python. Pure.

The schema is passed to `claude --json-schema`, but the model output is untrusted, so it is
validated again here. Error messages name fields and limits, never the model's text.
"""

import json
import math

MAX_CANDIDATES = 4
LIMITS = {"title": 160, "summary": 300, "body": 2500, "rationale": 200}
FIELDS = ("title", "summary", "body", "sourceThreadIds", "relevance", "rationale")


def _text(limit):
    return {"type": "string", "minLength": 1, "maxLength": limit}


PIECES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pieces"],
    "properties": {
        "pieces": {
            "type": "array",
            "maxItems": MAX_CANDIDATES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(FIELDS),
                "properties": {
                    "title": _text(LIMITS["title"]),
                    "summary": _text(LIMITS["summary"]),
                    "body": _text(LIMITS["body"]),
                    "sourceThreadIds": {"type": "array", "minItems": 1,
                                        "items": {"type": "string", "minLength": 1}},
                    "relevance": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": _text(LIMITS["rationale"]),
                },
            },
        },
    },
}


class SchemaError(Exception):
    """The model output does not match PIECES_SCHEMA."""


def schema_json():
    """The schema as one compact JSON line, for a single argv string."""
    return json.dumps(PIECES_SCHEMA, separators=(",", ":"))


def _string(value, where, limit):
    if not isinstance(value, str):
        raise SchemaError(f"{where}: expected a string")
    if not value.strip():
        raise SchemaError(f"{where}: empty")
    if len(value) > limit:
        raise SchemaError(f"{where}: longer than {limit} characters")
    return value


def _relevance(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{where}: expected a number")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise SchemaError(f"{where}: out of range 0..1")
    return float(value)


def _sources(value, where):
    if not isinstance(value, list):
        raise SchemaError(f"{where}: expected an array")
    if not value:
        raise SchemaError(f"{where}: empty")
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise SchemaError(f"{where}[{i}]: expected a string")
    return list(value)


def _piece(item, where):
    if not isinstance(item, dict):
        raise SchemaError(f"{where}: expected an object")
    extra = sorted(set(item) - set(FIELDS))
    if extra:
        raise SchemaError(f"{where}: unexpected field ({len(extra)})")
    for field in FIELDS:
        if field not in item:
            raise SchemaError(f"{where}.{field}: missing")
    clean = {field: _string(item[field], f"{where}.{field}", LIMITS[field])
             for field in ("title", "summary", "body")}
    clean["sourceThreadIds"] = _sources(item["sourceThreadIds"], f"{where}.sourceThreadIds")
    clean["relevance"] = _relevance(item["relevance"], f"{where}.relevance")
    clean["rationale"] = _string(item["rationale"], f"{where}.rationale", LIMITS["rationale"])
    return clean


def validate_output(data):
    """Validated copies of the pieces, in model order. Raises SchemaError."""
    if not isinstance(data, dict):
        raise SchemaError("output: expected an object")
    if "pieces" not in data:
        raise SchemaError("output.pieces: missing")
    if set(data) - {"pieces"}:
        raise SchemaError("output: unexpected field")
    pieces = data["pieces"]
    if not isinstance(pieces, list):
        raise SchemaError("pieces: expected an array")
    if len(pieces) > MAX_CANDIDATES:
        raise SchemaError(f"pieces: at most {MAX_CANDIDATES} candidates, got {len(pieces)}")
    return [_piece(item, f"pieces[{i}]") for i, item in enumerate(pieces)]
