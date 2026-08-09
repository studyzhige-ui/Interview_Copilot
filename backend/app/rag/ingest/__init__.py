"""Knowledge ingestion package.

Callers import concrete entry points from :mod:`app.rag.ingest.pipeline`; this
package intentionally performs no eager imports so index adapters can reuse the
embedding submodule without a circular dependency.
"""

__all__: list[str] = []
