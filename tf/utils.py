import json
from typing import Any, Optional, Tuple, cast

import msgpack
from msgpack.ext import ExtType

from tf.gen import tfplugin_pb2 as pb
from tf.types import Unknown


def _msgpack_default(obj: Any) -> Any:
    if obj is Unknown:
        return ExtType(0, b"\x00")

    return obj


def _msgpack_ext_hook(code, data) -> Any:
    if code == 0 and data == b"\x00":
        return Unknown

    return ExtType(code, data)


def read_dynamic_value(value: pb.DynamicValue) -> Any:
    if value.json:
        return json.loads(value.json)

    if value.msgpack:
        return msgpack.unpackb(value.msgpack, ext_hook=_msgpack_ext_hook)

    return None


def to_dynamic_value(value: Any) -> pb.DynamicValue:
    return pb.DynamicValue(msgpack=msgpack.packb(value, default=_msgpack_default) if value is not None else None)


AttributePath = list[str | Tuple[str | int]]


class Diagnostic:
    ERROR = "error"
    WARNING = "warning"
    INVALID = "invalid"  # is this used?

    _map = {
        "error": pb.Diagnostic.ERROR,
        "warning": pb.Diagnostic.WARNING,
        "invalid": pb.Diagnostic.INVALID,
    }

    def __init__(self, severity: str, summary: str, detail: Optional[str] = None, path: Optional[AttributePath] = None):
        self.severity = severity
        self.summary = summary
        self.detail = detail
        self.path = path

    @classmethod
    def error(cls, summary: str, detail: str = "", path: Optional[AttributePath] = None):
        return cls(cls.ERROR, summary, detail, path)

    @classmethod
    def warning(cls, summary: str, detail: str = "", path: Optional[AttributePath] = None):
        return cls(cls.WARNING, summary, detail, path)

    def to_pb(self) -> pb.Diagnostic:
        fields = {
            "severity": self._map[self.severity],
            "summary": self.summary,
            "detail": self.detail,
        }

        if self.path:
            fields["attribute"] = _to_attribute_path(self.path)

        return pb.Diagnostic(**fields)

    def __str__(self):
        path = (
            ""
            if self.path is None
            else " ({})".format(" -> ".join([step if isinstance(step, str) else str(list(step)) for step in self.path]))
        )
        detail = "" if not self.detail else f" :: {self.detail}"
        return f"{self.severity}{path}: {self.summary}{detail}"


def _to_attribute_path(path: AttributePath) -> pb.AttributePath:
    # TODO: Support str-index, int-index
    # If an element is "stringy" then we assume its an attribute name
    # If it's (123,) or ("elstring",) then we assume it's an int/str index
    return pb.AttributePath(steps=[_path_step(step) for step in path])


def _path_step(step_value: str | Tuple[str | int]) -> pb.AttributePath.Step:
    if isinstance(step_value, tuple):
        return (
            pb.AttributePath.Step(element_key_string=cast(str, step_value[0]))
            if isinstance(step_value[0], str)
            else pb.AttributePath.Step(element_key_int=cast(int, step_value[0]))
        )

    return pb.AttributePath.Step(attribute_name=step_value)


class Diagnostics:
    def __init__(self):
        self.diagnostics: list[Diagnostic] = []

    def add_error(self, *args, **kwargs):
        self.diagnostics.append(Diagnostic.error(*args, **kwargs))
        return self

    def add_warning(self, *args, **kwargs):
        self.diagnostics.append(Diagnostic.warning(*args, **kwargs))
        return self

    def to_pb(self) -> list[pb.Diagnostic]:
        return [d.to_pb() for d in self.diagnostics]

    def has_errors(self) -> bool:
        return any(d.severity == Diagnostic.ERROR for d in self.diagnostics)

    def has_warnings(self) -> bool:
        return any(d.severity == Diagnostic.WARNING for d in self.diagnostics)

    def __str__(self):
        error = ", with errors" if self.has_errors() else ""
        return f"diagnostics({len(self.diagnostics)}{error}) --" + "\n".join("\t " + str(d) for d in self.diagnostics)
