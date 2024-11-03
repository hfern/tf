from copy import copy, deepcopy
from unittest import TestCase

from tf import types
from tf.types import Unknown


class TypesTest(TestCase):
    def test_unknown_repr(self):
        # This makes it very easy to copy/paste from output to tests
        self.assertEqual(repr(Unknown), "Unknown")

    def test_unknown_copy_behavior(self):
        # Unknown is a singleton
        self.assertIs(Unknown, Unknown)
        self.assertEqual(Unknown, Unknown)
        self.assertEqual(id(Unknown), id(Unknown))
        self.assertIs(copy(Unknown), Unknown)
        self.assertIs(deepcopy(Unknown), Unknown)

    def test_integer_encoding(self):
        integer = types.Number()

        self.assertEqual(integer.encode(123), 123)
        self.assertEqual(integer.decode(123), 123)

    def test_string_encoding(self):
        string = types.String()

        self.assertEqual(string.encode("hello"), "hello")
        self.assertEqual(string.decode("hello"), "hello")

    def test_bool_encoding(self):
        boolean = types.Bool()

        self.assertEqual(boolean.encode(True), True)
        self.assertEqual(boolean.decode(True), True)

    def test_json_encoding(self):
        json = types.NormalizedJson()

        self.assertEqual(json.encode({"key": "value"}), '{"key": "value"}')
        self.assertEqual(json.decode('{"key":"value"}'), {"key": "value"})

    def test_json_encoding_normalization(self):
        json = types.NormalizedJson()

        self.assertEqual(
            json.encode({"key1": "value1", "key2": "value2"}),
            json.encode({"key2": "value2", "key1": "value1"}),
        )

    def test_list_encode(self):
        list_type = types.List(types.Number())

        self.assertEqual(list_type.encode(None), None)
        self.assertEqual(list_type.decode(None), None)

        self.assertEqual(list_type.encode(Unknown), Unknown)
        self.assertEqual(list_type.decode(Unknown), Unknown)

        self.assertEqual(list_type.encode([1, 2, 3]), [1, 2, 3])
        self.assertEqual(list_type.decode([1, 2, 3]), [1, 2, 3])

    def test_list_type_encoding(self):
        table = (
            (types.List(types.Number()), "list of int", b'["list","number"]'),
            (types.List(types.String()), "list of string", b'["list","string"]'),
            (types.List(types.Bool()), "list of bool", b'["list","bool"]'),
            (types.List(types.Set(types.Bool())), "list of set of bool", b'["list",["set","bool"]]'),
        )

        for set_type, test_name, expected in table:
            with self.subTest(test_name):
                self.assertEqual(set_type.tf_type(), expected)

    def test_list_equality(self):
        list_type = types.List(types.Number())

        self.assertTrue(list_type.semantically_equal([1, 2, 3], [1, 2, 3]))
        self.assertFalse(list_type.semantically_equal([1, 2, 3], [1, 2, 4]))
        self.assertFalse(list_type.semantically_equal([1, 2, 3], [1, 2]))

    def test_set_type_encoding(self):
        table = (
            (types.Set(types.Number()), "set of int", b'["set","number"]'),
            (types.Set(types.String()), "set of string", b'["set","string"]'),
            (types.Set(types.Bool()), "set of bool", b'["set","bool"]'),
            (types.Set(types.Set(types.Bool())), "set of set of bool", b'["set",["set","bool"]]'),
        )

        for set_type, test_name, expected in table:
            with self.subTest(test_name):
                self.assertEqual(set_type.tf_type(), expected)

    def test_set_semantic_equality(self):
        set_type = types.Set(types.Number())

        self.assertTrue(set_type.semantically_equal([1, 2, 3], [1, 2, 3]))
        self.assertFalse(set_type.semantically_equal([1, 2, 3], [1, 2, 4]))
        self.assertFalse(set_type.semantically_equal([1, 2, 3], [1, 2]))
        self.assertTrue(set_type.semantically_equal([1, 2, 3], [3, 2, 1]))
        self.assertTrue(set_type.semantically_equal(set(), set()))
        self.assertTrue(set_type.semantically_equal(None, None))
        self.assertTrue(set_type.semantically_equal(Unknown, Unknown))
