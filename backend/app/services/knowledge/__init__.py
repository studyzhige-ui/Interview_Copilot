"""Knowledge document lifecycle services.

  knowledge_service        — CRUD for KnowledgeDocument rows; deletes Milvus
                             vectors + document_chunks on hard delete
  document_chunk_service   — read/write the ``document_chunks`` fact table
"""
