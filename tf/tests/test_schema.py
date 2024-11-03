from unittest import TestCase

from tf.gen import tfplugin_pb2 as pb
from tf.schema import Schema


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
