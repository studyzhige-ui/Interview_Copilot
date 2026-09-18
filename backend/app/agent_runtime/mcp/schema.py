"""Validate remote contracts without retrieving untrusted external references."""

from jsonschema import Draft202012Validator
from referencing import Registry


def tool_validator(schema: dict) -> Draft202012Validator:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ValueError("MCP tool input schema must be an object")
    Draft202012Validator.check_schema(schema)
    # The empty registry never fetches a URL. Local $defs/$ref still work.
    return Draft202012Validator(schema, registry=Registry())
