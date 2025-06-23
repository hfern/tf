from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StdioData(_message.Message):
    __slots__ = ("channel", "data")
    class Channel(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        INVALID: _ClassVar[StdioData.Channel]
        STDOUT: _ClassVar[StdioData.Channel]
        STDERR: _ClassVar[StdioData.Channel]
    INVALID: StdioData.Channel
    STDOUT: StdioData.Channel
    STDERR: StdioData.Channel
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    channel: StdioData.Channel
    data: bytes
    def __init__(self, channel: _Optional[_Union[StdioData.Channel, str]] = ..., data: _Optional[bytes] = ...) -> None: ...
