# Owned CPU document parsing and OCR

Docling no longer imports or loads model packages in its API/application caller.
The parser selector does a package-presence check only. The same `DoclingParser`
contract dispatches to an owned fresh interpreter via the existing
`run_isolated` process-group lifecycle. `PARSER_LOCAL_PYTHON` optionally selects a
separate CPU environment pinned by `requirements/local-document.txt`; empty uses
the current interpreter when Docling is installed there. The child checks the
Docling 2.118.1 version before conversion and never imports the application .env.

One parser slot per application process stays owned until the child exits and
its process group is reaped. Queue time, input capture and execution share a
finite deadline; thread-waiter cancellation does not delete an in-use snapshot.
A private, read-only disk snapshot keeps the original extension and a SHA256
identity. Symlinks, special files, source replacement and size overflow fail.
The child validates that snapshot and the parent rechecks original source
identity before returning. A changed source cannot be read by a fallback parser.

CPU-only AcceleratorOptions and hidden CUDA devices prevent this supported
Docling path from competing with the GPU speech broker. This is not a new GPU
scheduler or an OS/native-code security sandbox. The child receives no provider
or database credentials, has explicit offline SDK flags, and denies Python
network connect/DNS/send operations. Docling receives only a local snapshot and
explicit local artifact root; remote services and external plugins are disabled.
Missing local assets fail rather than downloading or switching to cloud.

The SDK receives max page/file limits and a document timeout; PARTIAL_SUCCESS is
rejected, not published as a full document. Page numbers survive Markdown export
and canonical cleaning. Aggregate UTF-8 output and the JSON/log pipe are bounded.
Images report OCR when it was enabled; PDFs do not pretend every page used OCR.
Actual OCR enablement, package version and the isolated CPU contract are recorded
in parser provenance. A parser contract version change gives new indexes a new
identity; historical generations are not relabelled or silently rebuilt.

The normal registry still permits its existing explicit, format-specific local
fallback. Text formats do not require a remote service; images without usable
OCR fail with the existing empty-content error. No parser failure permits cloud
fallback under local-only policy. RAG_DEVICE is not a bypass into unreserved GPU
parsing. Interpreter cold-start/model load costs and OCR accuracy require local
measurements; deterministic tests and SDK substitutes do not certify quality.

Validated SDK interfaces (no source PDF or model weights downloaded in this work):
- https://github.com/docling-project/docling/blob/v2.118.1/docling/datamodel/pipeline_options.py
- https://github.com/docling-project/docling/blob/v2.118.1/docling/document_converter.py
- https://docling-project.github.io/docling/usage/advanced_options/

## Offline code grammar boundary

The pinned generic tree-sitter language pack fetched a grammar manifest and native
library at the first code ingestion. It is replaced by four explicit installed
grammar wheels (Python 0.25.0, Java 0.23.5, C++ 0.23.4, C 0.24.1). C now uses its
own grammar. The chunker contract version changes, so a new index generation is
required rather than silently mixing differently chunked facts. An exhaustive
four-format test denies network lookup/connect and exercises the real parsers.
Package installation may download wheels; application ingestion must not.

Local deterministic checks cover private snapshot lifetime, replacement on both
success and failure, strict request/result contracts, page provenance, timeout and
credential-free CPU child dispatch, SDK option forwarding, partial-conversion
rejection and a fresh interpreter round-trip using an explicit SDK substitute.
The broader parser/model-asset campaign passes 55 tests locally. Actual Docling
weights and OCR quality were not exercised. Real grammar-wheel and full combined
verification runs in the integration environment with the pinned dependencies.
