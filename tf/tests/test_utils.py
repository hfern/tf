from unittest import TestCase

from msgpack.ext import ExtType

from tf import utils
from tf.gen import tfplugin_pb2 as pb
from tf.types import Unknown
from tf.utils import Diagnostic


class DynamicValueTest(TestCase):
    def test_encode(self):
        tests = {
            "integer": (123, b"\x7b"),
            "negative one": (-1, b"\xff"),
            "float": (1.23, b"\xcb\x3f\xf3\xae\x14\x7a\xe1\x47\xae"),
            "map": ({"key": "value"}, b"\x81\xa3key\xa5value"),
            "array": ([1, 2, 3], b"\x93\x01\x02\x03"),
            "unknown": (Unknown, b"\xd4\x00\x00"),
        }

        for case_name, (value, expected) in tests.items():
            with self.subTest(case_name):
                self.assertEqual(expected, utils.to_dynamic_value(value).msgpack)

    def test_decode(self):
        tests = {
            "integer": (b"\x7b", 123),
            "negative one": (b"\xff", -1),
            "float": (b"\xcb\x3f\xf3\xae\x14\x7a\xe1\x47\xae", 1.23),
            "map": (b"\x81\xa3key\xa5value", {"key": "value"}),
            "array": (b"\x93\x01\x02\x03", [1, 2, 3]),
            "unknown": (b"\xd4\x00\x00", Unknown),
            "ext1-other": (b"\xd4\x01\x00", ExtType(code=1, data=b"\x00")),
        }

        for case_name, (msgpack, expected) in tests.items():
            with self.subTest(case_name):
                self.assertEqual(expected, utils.read_dynamic_value(pb.DynamicValue(msgpack=msgpack)))

    def test_decode_json(self):
        """JSON is passed in very rarely, and never for state planning so we don't have to test Unknown"""
        tests = {
            "integer": ("123", 123),
            "negative one": ("-1", -1),
            "float": ("1.23", 1.23),
            "map": ('{"key":"value"}', {"key": "value"}),
            "array": ("[1,2,3]", [1, 2, 3]),
            "null": ("null", None),
        }

        for case_name, (value, expected) in tests.items():
            with self.subTest(case_name):
                self.assertEqual(
                    expected,
                    utils.read_dynamic_value(pb.DynamicValue(json=value.encode())),
                )

    def test_decode_none(self):
        self.assertIsNone(utils.read_dynamic_value(pb.DynamicValue()))

    def test_ext_encoder(self):
        self.assertEqual(123, utils._msgpack_default(123))
        self.assertEqual(ExtType(0, b"\x00"), utils._msgpack_default(Unknown))


class DiagnosticsTest(TestCase):
    def test_has_errors(self):
        diags = utils.Diagnostics()
        self.assertFalse(diags.has_errors())

        diags.add_error("error")
        self.assertTrue(diags.has_errors())

    def test_has_warnings(self):
        diags = utils.Diagnostics()
        self.assertFalse(diags.has_warnings())

        diags.add_warning("error")
        self.assertTrue(diags.has_warnings())

    def test_path(self):
        diags = utils.Diagnostics()
        diags.add_error("error", path=["a", (1,), ("stringy",)])
        self.assertEqual(
            diags.to_pb(),
            [
                pb.Diagnostic(
                    severity=pb.Diagnostic.ERROR,
                    summary="error",
                    attribute=pb.AttributePath(
                        steps=[
                            pb.AttributePath.Step(attribute_name="a"),
                            pb.AttributePath.Step(element_key_int=1),
                            pb.AttributePath.Step(element_key_string="stringy"),
                        ],
                    ),
                ),
            ],
        )

    def test_str(self):
        diag = Diagnostic.error("err summary", path=["a", (1,), ("stringy",)])
        self.assertEqual(
            str(diag),
            "error (a -> [1] -> ['stringy']): err summary",
        )
