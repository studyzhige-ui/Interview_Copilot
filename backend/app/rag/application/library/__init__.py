"""Knowledge document lifecycle services.

  knowledge_service        — CRUD for KnowledgeDocument rows; deletes canonical
                             retrieval entries and chunks on hard delete
  document_formats         — upload format whitelist + validation
  index_jobs               — durable retrieval projection job producers
  qa_publish_service       — publish interview QAs as knowledge documents

Chunk-level modules (``document_chunk_service`` fact table read/write and
``chunk_hydration``) live in ``app.rag`` — they are stages of the RAG
ingest/retrieval pipeline, not document-lifecycle services.
"""
