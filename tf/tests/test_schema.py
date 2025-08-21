from unittest import TestCase

from tf.gen import tfplugin_pb2 as pb
from tf.schema import Schema, TextFormat


class SchemaTest(TestCase):
    def test_encode_empty(self):
        schema = Schema()
        self.assertEqual(
            schema.to_pb(),
            pb.Schema(block=pb.Schema.Block(attributes=[])),
        )

    def test_version_encode(self):
        schema = Schema(version=9)
        self.assertEqual(
            schema.to_pb(),
            pb.Schema(
                version=9,
                block=pb.Schema.Block(attributes=[]),
            ),
        )

    def test_encode_description(self):
        schema = Schema(
            description="This is a test schema",
        )
        self.assertEqual(
            schema.to_pb(),
            pb.Schema(
                block=pb.Schema.Block(
                    description="This is a test schema",
                    description_kind="MARKDOWN",
                ),
            ),
        )

    def test_encode_description_plain(self):
        schema = Schema(
            description="This is a test schema",
            description_kind=TextFormat.Plain,
        )
        self.assertEqual(
            schema.to_pb(),
            pb.Schema(
                block=pb.Schema.Block(
                    description="This is a test schema",
                    description_kind="PLAIN",
                ),
            ),
        )

    def test_encode_deprecated(self):
        schema = Schema(
            deprecated=True,
        )
        self.assertEqual(
            schema.to_pb(),
            pb.Schema(
                block=pb.Schema.Block(
                    deprecated=True,
                ),
            ),
        )
