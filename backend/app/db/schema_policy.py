"""Separate operator-owned physical indexes from declarative migrations."""

import re


def include_schema_object(obj, name, type_, reflected, compare_to):
    """Keep provisioned owner graphs without hiding other schema differences."""
    operator_graph = (
        type_ == "index"
        and reflected
        and compare_to is None
        and re.fullmatch(r"ix_rag_hnsw_[0-9a-f]{40}", name or "") is not None
        and obj.table.name == "retrieval_entries"
        and obj.dialect_options["postgresql"]["using"] == "hnsw"
    )
    return not operator_graph
