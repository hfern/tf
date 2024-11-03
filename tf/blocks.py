from typing import Any

from tf.schema import Block, NestedBlock, NestMode

# class SingleNestedBlock(NestedBlock):
#     def __init__(self, type_name: str, block: Block, required: Optional[bool] = False):
#         more = {"min_items": 1, "max_items": 1} if required else {}
#         super().__init__(type_name, NestMode.Single, block, **more)
#
#     def encode(self, value: Any) -> Any:
#         from tf.provider import _encode_state_d
#
#         return _encode_state_d(self._amap(), self._bmap(), value, None)
#
#     def decode(self, value: Any) -> Any:
#         from tf.provider import _decode_state
#
#         return _decode_state(self._amap(), self._bmap(), value)[1]


class SetNestedBlock(NestedBlock):
    # State is encoded as a list of dicts, where the dicts are the substates

    def __init__(self, type_name: str, block: Block):
        super().__init__(type_name, NestMode.Set, block)

    def encode(self, value: Any) -> Any:
        from tf.provider import _encode_state_d

        return [_encode_state_d(self._amap(), self._bmap(), v, None) for v in value]

    def decode(self, value: Any) -> Any:
        from tf.provider import _decode_state

        return [_decode_state(self._amap(), self._bmap(), v)[1] for v in value]

    def semantically_equal(self, a_decoded, b_decoded) -> bool:
        # Since this is a set, we turn the block into a tuple
        # and then compare tuples
        # Kinda gross?
        # TODO(Hunter): Support nested nested blocks instead of just attrs
        # You know, doesn't this kind of have a bug in it?
        # Two elements should be equal if they have the same SEMANTIC equality

        if len(a_decoded) != len(b_decoded):
            return False

        if len(a_decoded) == 0:
            return True

        def to_tuple(d):
            return tuple([d.get(attr.name, None) for attr in self.block.attributes])

        a_tuples = [to_tuple(d) for d in a_decoded]
        b_tuples = [to_tuple(d) for d in b_decoded]

        # Each tuple of a is in b and vice versa
        for a in a_tuples:
            if a not in b_tuples:
                return False

        for b in b_tuples:
            if b not in a_tuples:
                return False

        return True
