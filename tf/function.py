from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from tf.gen import tfplugin_pb2 as pb
from tf.schema import TextFormat, _desc_format_map
from tf.types import TfType
from tf.utils import Diagnostics


@dataclass
class Parameter:
    """
    Represents a function parameter.

    :param name: The name of the parameter
    :param type: The type of the parameter
    :param description: Human-readable description
    :param description_kind: Format of the description (defaults to Markdown)
    :param allow_null_value: Whether null values are allowed
    :param allow_unknown_values: Whether unknown values are allowed
    """

    name: str
    type: TfType
    description: Optional[str] = None
    description_kind: Optional[TextFormat] = None
    allow_null_value: bool = False
    allow_unknown_values: bool = False

    def to_pb(self) -> pb.Function.Parameter:
        return pb.Function.Parameter(
            name=self.name,
            type=self.type.tf_type(),
            description=self.description,
            description_kind=_desc_format_map.get(self.description_kind) if self.description_kind else None,
            allow_null_value=self.allow_null_value,
            allow_unknown_values=self.allow_unknown_values,
        )


@dataclass
class Return:
    """
    Represents a function return value.

    :param type: The type of the return value
    """

    type: TfType

    def to_pb(self) -> pb.Function.Return:
        return pb.Function.Return(type=self.type.tf_type())


@dataclass
class FunctionSignature:
    """
    Represents the signature of a provider function.

    :param parameters: Ordered list of positional parameters
    :param variadic_parameter: Optional final parameter that accepts zero or more values
    :param return_type: The return type
    :param summary: Short human-readable documentation
    :param description: Detailed human-readable documentation
    :param description_kind: Format of the description (defaults to Markdown)
    :param deprecation_message: Message if function is deprecated
    """

    parameters: list[Parameter]
    return_type: Return
    variadic_parameter: Optional[Parameter] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    description_kind: Optional[TextFormat] = None
    deprecation_message: Optional[str] = None

    def to_pb(self) -> pb.Function:
        func = pb.Function(
            parameters=[p.to_pb() for p in self.parameters],
            variadic_parameter=self.variadic_parameter.to_pb() if self.variadic_parameter else None,
            summary=self.summary,
            description=self.description,
            description_kind=_desc_format_map.get(self.description_kind) if self.description_kind else None,
            deprecation_message=self.deprecation_message,
        )
        # Use getattr to access 'return' field because it's a reserved keyword in Python
        getattr(func, "return").CopyFrom(self.return_type.to_pb())  # pyre-ignore[16]
        return func


@dataclass
class CallContext:
    """Context provided to function calls"""

    diagnostics: Diagnostics
    function_name: str


class Function(Protocol):
    """Protocol for provider functions"""

    @classmethod
    @abstractmethod
    def get_name(cls) -> str:
        """Get the name of the function"""

    @classmethod
    @abstractmethod
    def get_signature(cls) -> FunctionSignature:
        """Get the function signature"""

    @abstractmethod
    def call(self, ctx: CallContext, arguments: list[Any]) -> Any:
        """
        Execute the function with the given arguments.

        :param ctx: The call context with diagnostics
        :param arguments: List of decoded argument values
        :return: The function result
        """
