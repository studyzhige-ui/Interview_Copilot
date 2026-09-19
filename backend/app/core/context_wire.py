"""Drop internal projection metadata only at the transport boundary."""


def wire(messages: list[dict]) -> list[dict]:
    return [
        {k: v for k, v in message.items() if k != "_context"} for message in messages
    ]
