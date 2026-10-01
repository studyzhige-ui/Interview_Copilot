"""Dependency-free protocol failures shared by control and media codecs."""


class ProtocolError(ValueError):
    """A bounded local inference message violates the wire contract."""
