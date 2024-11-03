from unittest import TestCase

from tf import types as t
from tf.blocks import Block, SetNestedBlock
from tf.gen import tfplugin_pb2 as pb
from tf.schema import Attribute


class SetNestedBlockTest(TestCase):
    def test_equality(self):
        set_block = SetNestedBlock(
            "test",
            Block(
                [
                    Attribute("name", t.String()),
                    Attribute("age", t.Number()),
                ]
            ),
        )

        a = [{"name": "a", "age": 1}, {"name": "b", "age": 2}]
        b = [{"name": "b", "age": 2}, {"name": "a", "age": 1}]

        self.assertTrue(set_block.semantically_equal([], []))
        self.assertTrue(set_block.semantically_equal(a, b))
        self.assertTrue(set_block.semantically_equal(b, a))
        self.assertTrue(set_block.semantically_equal(a, list(reversed(b))))

        self.assertFalse(set_block.semantically_equal([], a))
        self.assertFalse(set_block.semantically_equal(a, []))
        self.assertFalse(set_block.semantically_equal([{"name": "a", "age": 1}], a))
        self.assertFalse(set_block.semantically_equal(a, [{"name": "a", "age": 1}]))

        self.assertFalse(
            set_block.semantically_equal(
                [{"name": "a", "age": 1}, {"name": "a", "age": 1}],
                [{"name": "a", "age": 1}, {"name": "b", "age": 2}],
            )
        )

    def test_encoding(self):
        set_block = SetNestedBlock(
            "test",
            Block(
                [
                    Attribute("name", t.String()),
                    Attribute("age", t.Number()),
                ]
            ),
        )

        self.assertEqual(
            set_block.to_pb(),
            pb.Schema.NestedBlock(
                type_name="test",
                nesting=pb.Schema.NestedBlock.NestingMode.SET,
                block=pb.Schema.Block(
                    attributes=[
                        pb.Schema.Attribute(name="name", type=b'"string"', description_kind="MARKDOWN"),
                        pb.Schema.Attribute(name="age", type=b'"number"', description_kind="MARKDOWN"),
                    ],
                ),
            ),
        )
