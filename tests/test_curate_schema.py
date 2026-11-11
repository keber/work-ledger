import json
import unittest

from tests.curatefixtures import output, piece
from work_ledger.curate_schema import (MAX_CANDIDATES, PIECES_SCHEMA, SchemaError, schema_json,
                                       validate_output)


class SchemaTest(unittest.TestCase):
    def test_schema_limits_match_the_spec(self):
        pieces = PIECES_SCHEMA["properties"]["pieces"]
        props = pieces["items"]["properties"]
        self.assertEqual(MAX_CANDIDATES, 4)
        self.assertEqual(pieces["maxItems"], 4)
        self.assertEqual(props["summary"]["maxLength"], 300)
        self.assertEqual(props["body"]["maxLength"], 2500)
        self.assertEqual(props["rationale"]["maxLength"], 200)
        self.assertEqual((props["relevance"]["minimum"], props["relevance"]["maximum"]), (0, 1))
        self.assertEqual(set(pieces["items"]["required"]),
                         {"title", "summary", "body", "sourceThreadIds", "relevance",
                          "rationale"})
        self.assertFalse(PIECES_SCHEMA["additionalProperties"])

    def test_schema_json_is_one_compact_line(self):
        text = schema_json()
        self.assertNotIn("\n", text)
        self.assertEqual(json.loads(text), PIECES_SCHEMA)


class ValidateTest(unittest.TestCase):
    def assert_invalid(self, data, fragment):
        with self.assertRaises(SchemaError) as ctx:
            validate_output(data)
        self.assertIn(fragment, str(ctx.exception))

    def test_valid_output_returns_clean_copies(self):
        data = output(piece(relevance=1), piece(relevance=0))
        self.assertEqual(validate_output(data), data["pieces"])
        self.assertEqual(validate_output(output()), [])

    def test_integer_relevance_is_accepted(self):
        self.assertEqual(validate_output(output(piece(relevance=1)))[0]["relevance"], 1.0)

    def test_top_level_shape(self):
        self.assert_invalid([], "expected an object")
        self.assert_invalid({}, "pieces")
        self.assert_invalid({"pieces": {}}, "pieces: expected an array")
        self.assert_invalid({"pieces": [], "extra": 1}, "unexpected field")
        self.assert_invalid(output(*[piece()] * 5), "at most 4")

    def test_piece_fields(self):
        cases = [
            (dict(piece(), extra=1), "unexpected field"),
            ({k: v for k, v in piece().items() if k != "body"}, "pieces[0].body: missing"),
            (piece(title=""), "pieces[0].title: empty"),
            (piece(title=3), "pieces[0].title: expected a string"),
            (piece(summary="x" * 301), "longer than 300"),
            (piece(body="x" * 2501), "longer than 2500"),
            (piece(rationale="x" * 201), "longer than 200"),
            (piece(relevance=1.5), "relevance: out of range"),
            (piece(relevance=-0.1), "relevance: out of range"),
            (piece(relevance=True), "relevance: expected a number"),
            (piece(relevance=float("nan")), "relevance: out of range"),
            (piece(sources=()), "sourceThreadIds: empty"),
            (dict(piece(), sourceThreadIds="a"), "sourceThreadIds: expected an array"),
            (piece(sources=("a", 2)), "sourceThreadIds[1]: expected a string"),
        ]
        for bad, fragment in cases:
            with self.subTest(fragment=fragment):
                self.assert_invalid(output(bad), fragment)

    def test_errors_do_not_echo_model_text(self):
        with self.assertRaises(SchemaError) as ctx:
            validate_output(output(piece(summary="SECRET " * 60)))
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_title_is_bounded(self):
        self.assert_invalid(output(piece(title="x" * 161)), "longer than 160")


if __name__ == "__main__":
    unittest.main()
