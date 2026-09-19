"""Transport-independent command failures shared by application owners."""


class CommandError(Exception):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        self.message = message
        super().__init__(message)
