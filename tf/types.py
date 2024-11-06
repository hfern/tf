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
        return json.loads(value) if value not in (None, Unknown) else value

    def semantically_equal(self, a_decoded, b_decoded) -> bool:
        # This is hilariously inefficient but meh
        return self.encode(a_decoded) == self.encode(b_decoded)


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

        a = list(a_decoded)  # op[tional set => list
        b = list(b_decoded)  # optional set => list

        if len(a) == len(b) == 0:
            return True

        if len(a) != len(b):
            return False

        # Super gross, super inefficient, revisit
        # Sets are equal iff every element in a is in b and vice versa
        # (unfortunately, we don't deal with the deduplication logic)
        # (python dict comparison is doing a lot of work here)
        return all(a_ in b and b_ in a for a_, b_ in zip(a, b))


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


# Unknown is a meta type that can be used to represent an unknown value in a state plan
Unknown = _Unknown()
