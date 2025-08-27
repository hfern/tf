import json
from abc import abstractmethod
from typing import Any, Protocol

# https://github.com/zclconf/go-cty/blob/0b7ccb8423606ba894cc0e3b71375386e4d564de/cty/json.go#L104
# https://github.com/opentofu/opentofu/blob/0d1e6cd5f0a23e9abdff8a583dce25c54c3701b3/docs/plugin-protocol/object-wire-format.md
_T_INT = b'"number"'
_T_STR = b'"string"'
_T_BOOL = b'"bool"'


class TfType(Protocol):
    @abstractmethod
    def encode(self, value: Any) -> Any:
        """Encode the python representation into the tf-serializable"""
        # Structure the value into something encodable by messagepack

    @abstractmethod
    def decode(self, value: Any) -> Any:
        """Decode the tf-serializable representation into the python representation"""
        # In practice this means messagepack wire format, which in practice means its already structured

    def semantically_equal(self, a_decoded, b_decoded) -> bool:
        """
        Check if two Python-types (represented by the implementing type) are semantically equal.
        For Integers, ints will be passed in, and so on.
        """
        return a_decoded == b_decoded

    @abstractmethod
    def tf_type(self) -> bytes:
        """Return the TF type pattern"""


class Number(TfType):
    """
    Numbers are numeric values. They can be integers or floats.
    Maps to Python `int` or `float`.

    Usually this is fine, but if you need to distinguish between the two you
    must do it in your Resource CRUD implementation.
    """

    def encode(self, value: Any) -> Any:
        return value  # native

    def decode(self, value: Any) -> Any:
        return value  # native

    def tf_type(self) -> bytes:
        return _T_INT


class String(TfType):
    """Strings are sequences of characters. Maps to Python `str`."""

    def encode(self, value: Any) -> Any:
        return value  # native

    def decode(self, value: Any) -> Any:
        return value  # native

    def tf_type(self) -> bytes:
        return _T_STR


class Bool(TfType):
    """True or False. Maps to Python `bool`."""

    def encode(self, value: Any) -> Any:
        return value  # native

    def decode(self, value: Any) -> Any:
        return value  # native

    def tf_type(self) -> bytes:
        return _T_BOOL


class NormalizedJson(String):
    """
    JSON type that doesn't care about the order of keys.

    Under the hood, this is just a string in the state file.
    """

    # The trick is that we always just sort the keys when
    # encoding so TF always sees the string as exactly the same

    def encode(self, value: Any) -> Any:
        return json.dumps(value, sort_keys=True) if value not in (None, Unknown) else value

    def decode(self, value: Any) -> Any:
        try:
            return json.loads(value) if value not in (None, Unknown) else value
        except json.JSONDecodeError as e:
            raise ValueError(f"Error parsing JSON: {e}") from e

    def semantically_equal(self, a_decoded, b_decoded) -> bool:
        # Direct comparison is sufficient for normalized JSON
        # since json.loads/dumps with sort_keys normalizes the data
        return a_decoded == b_decoded


class List(TfType):
    """
    Lists are ordered collections of homogeneously-typed values. Maps to Python `list`.

    :param element_type: The type of the elements in the list.
    """

    def __init__(self, element_type: TfType):
        self.element_type = element_type

    def encode(self, value: Any) -> Any:
        if value in (None, Unknown):
            return value

        return [self.element_type.encode(v) for v in value]

    def decode(self, value: Any) -> Any:
        if value in (None, Unknown):
            return value

        return [self.element_type.decode(v) for v in value]

    def tf_type(self) -> bytes:
        t = self.element_type.tf_type().decode()
        return f'["list",{t}]'.encode()


class Set(List):
    """
    Sets are collections of homogeneously-typed values.
    Sets are represented as lists in Python because TF Sets can have object values, which Python doesn't like.
    Maps to Python `list`.

    OK in TF, Bad in Python: `set(({"a": 123},))`

    Result: `TypeError: unhashable type: 'dict'`

    :param element_type: The type of the elements in the set.
    """

    def tf_type(self) -> bytes:
        t = self.element_type.tf_type().decode()
        return f'["set",{t}]'.encode()

    def semantically_equal(self, a_decoded, b_decoded) -> bool:
        if a_decoded is b_decoded:  # None or Unknown or literally the same
            return True

        # Convert to lists to handle both set and list inputs
        a = list(a_decoded) if a_decoded is not None else []
        b = list(b_decoded) if b_decoded is not None else []

        if len(a) != len(b):
            return False

        if len(a) == 0:
            return True

        # For sets, order doesn't matter, so we need to check that
        # every element in a has a matching element in b
        # Convert to string for comparison since all TF values can be stringified
        return sorted(map(str, a)) == sorted(map(str, b))


# Map
# Object
# Tuple
# Dynamic?


class _Unknown:
    def __repr__(self):
        return "Unknown"

    def __copy__(self):
        # Singleton
        return self

    def __deepcopy__(self, memo):
        # Singleton id(deepcopy(Unknown)) == id(Unknown)
        return self


Unknown = _Unknown()
"""
Unknown is a sentinel value that represents a value that is not yet known.
You will find these in a state plan.
"""
