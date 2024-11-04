from abc import abstractmethod
from enum import Enum
from typing import Any, Optional, cast

from tf.gen import tfplugin_pb2 as pb
from tf.types import TfType, Unknown


class TextFormat(Enum):
    Plain = "plain"
    Markdown = "markdown"


_desc_format_map = {
    TextFormat.Plain: pb.StringKind.PLAIN,
    TextFormat.Markdown: pb.StringKind.MARKDOWN,
}


class Attribute:
    """
    An attribute is a single field in a schema.

    :param name: Name of the attribute
    :param type: Type of the attribute
    :param description: Description of the attribute
    :param required: Required?
    :param optional: Optional?
    :param computed: Computed?
    :param sensitive: Sensitive?
    :param description_kind: Description kind (defaults to Markdown)
    :param deprecated: Deprecated?
    :param requires_replace: Should a change of this value require a replace of the resource?
    :param default: If this value is computed but not set, this will be the default value in the change plan
    """

    def __init__(
        self,
        name: str,
        type: TfType,
        description: Optional[str] = None,
        required: Optional[bool] = False,
        optional: Optional[bool] = False,
        computed: Optional[bool] = False,
        sensitive: Optional[bool] = False,
        description_kind: Optional[TextFormat] = None,
        deprecated: Optional[bool] = None,
        # -- Simplified provider logic --
        # Will changing this attribute require a replace of the resource?
        # Some fields are immutable and changing them requires a new resource to be created
        requires_replace: Optional[bool] = None,
        read_only: Optional[bool] = False,  # TODO(Hunter): Actually enforce this in CREATE/UPDATE
        # If computed and not set by the caller, what should the default value be?
        default: Any = Unknown,
    ):
        self.name = name
        self.type = type
        self.description = description
        self.required = required
        self.optional = optional
        self.computed = computed
        self.sensitive = sensitive
        self.description_kind = description_kind
        self.deprecated = deprecated
        self.requires_replace = requires_replace
        self.default = default

    def to_pb(self) -> pb.Schema.Attribute:
        can_be_null = dict(
            description=self.description,
            required=self.required or None,
            optional=self.optional or None,
            computed=self.computed or None,
            sensitive=self.sensitive,
            deprecated=self.deprecated,
        )

        return pb.Schema.Attribute(
            name=self.name,
            type=self.type.tf_type(),
            description_kind=_desc_format_map[self.description_kind or TextFormat.Markdown],
            **can_be_null,  # pyre-ignore[6]: we can actually pass in Nones here for defaults
        )


class Schema:
    """
    A schema is a description of the data model for a resource type.

    :param attributes: List of attributes
    :param version: Version of the schema
    :param block_types: List of nested block types

    Example::

        from tf.schema import Schema, Attribute
        from tf.types import Number

        schema = schema.Schema(
            version=2,
            attributes=[
                schema.Attribute("a", types.Number(), required=True),
                schema.Attribute("b", types.Number(), required=True, requires_replace=True),
                schema.Attribute("sum", types.Number(), computed=True),
            ],
        )
    """

    def __init__(
        self,
        attributes: Optional[list[Attribute]] = None,
        version: Optional[int] = None,
        block_types: Optional[list["NestedBlock"]] = None,
    ):
        self.attributes = attributes or []
        self.version: Optional[int] = version
        self.block_types = block_types or []

    def to_pb(self) -> pb.Schema:
        more = {"version": self.version} if self.version is not None else {}

        return pb.Schema(
            block=Block(attributes=self.attributes, block_types=self.block_types).to_pb(),
            **more,
        )


class Block:
    def __init__(self, attributes: Optional[list[Attribute]] = None, block_types: Optional[list["NestedBlock"]] = None):
        self.attributes = attributes or []
        self.block_types = block_types or []

    def to_pb(self) -> pb.Schema.Block:
        more = {
            "block_types": [nb.to_pb() for nb in self.block_types] or None,
        }

        not_none = {k: v for k, v in more.items() if v is not None}

        return pb.Schema.Block(
            attributes=[attr.to_pb() for attr in self.attributes],
            **cast(dict, not_none),
        )


class NestMode(Enum):
    Set = "set"
    Single = "single"


class NestedBlock:
    _mode_map = {
        NestMode.Set: pb.Schema.NestedBlock.NestingMode.SET,
        NestMode.Single: pb.Schema.NestedBlock.NestingMode.SINGLE,
    }

    def __init__(
        self,
        type_name: str,
        nesting_mode: NestMode,
        block: Block,
        min_items: Optional[int] = None,
        max_items: Optional[int] = None,
    ):
        self.type_name = type_name
        self.block = block
        self.min_items = min_items
        self.max_items = max_items
        self.nesting_mode = nesting_mode

    def to_pb(self) -> pb.Schema.NestedBlock:
        return pb.Schema.NestedBlock(
            type_name=self.type_name,
            block=self.block.to_pb(),
            min_items=self.min_items,
            max_items=self.max_items,
            nesting=self._mode_map[self.nesting_mode],
        )

    @abstractmethod
    def encode(self, value: Any) -> Any:
        """Encode the python representation into the tf-serializable"""

    @abstractmethod
    def decode(self, value: Any) -> Any:
        """Decode the tf-serializable representation into the python representation"""

    @abstractmethod
    def semantically_equal(self, a_decoded, b_decoded) -> bool:
        """
        Check if two Python-types (represented by the implementing type) are semantically equal.
        For Integers, ints will be passed in, and so on.
        """

    def _amap(self) -> dict[str, Attribute]:
        return {a.name: a for a in self.block.attributes}

    def _bmap(self) -> dict[str, "NestedBlock"]:
        return {b.type_name: b for b in self.block.block_types}
