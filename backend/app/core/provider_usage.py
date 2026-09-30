"""Usage event semantics shared by every streaming consumer.

Missing counters are not zero. Native providers may publish input/output in
separate events; normalized observations preserve which partition was present.
Cache counts are disjoint from uncached input only at the ledger projection.
"""


def counter(value: object, *, default: int = 0) -> int:
    if value is None:
        return default
    if type(value) is not int or not 0 <= value <= 2**31 - 1:
        raise ValueError("invalid_provider_usage")
    return value


def accumulate(target: dict[str, int], observation: object) -> None:
    for name in (
        "prompt_tokens",
        "completion_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
    ):
        known = "output_known" if name == "completion_tokens" else "input_known"
        if not getattr(observation, known, True):
            continue
        value = counter(getattr(observation, name, None))
        target[name] = max(target.get(name, 0), value)
    if (
        "prompt_tokens" in target
        and target.get("cache_read_tokens", 0) + target.get("cache_creation_tokens", 0)
        > target["prompt_tokens"]
    ):
        raise ValueError("cache_usage_exceeds_input")


def ledger_units(usage: dict[str, int]) -> dict[str, int] | None:
    if not usage:
        return None
    values = {"requests": 1}
    if "prompt_tokens" in usage:
        prompt = counter(usage["prompt_tokens"])
        read = counter(usage.get("cache_read_tokens"))
        write = counter(usage.get("cache_creation_tokens"))
        if read + write > prompt:
            raise ValueError("cache_usage_exceeds_input")
        values.update(
            input_tokens=prompt - read - write,
            cache_read_tokens=read,
            cache_write_tokens=write,
        )
    if "completion_tokens" in usage:
        values["output_tokens"] = counter(usage["completion_tokens"])
    return values


def logical_tokens(usage: dict[str, int]) -> int | None:
    if not {"prompt_tokens", "completion_tokens"}.issubset(usage):
        return None
    return counter(usage["prompt_tokens"]) + counter(usage["completion_tokens"])
