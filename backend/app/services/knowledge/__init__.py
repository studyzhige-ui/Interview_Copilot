"""Knowledge document lifecycle services.

  knowledge_service       — CRUD for KnowledgeDocument rows; deletes
                            Milvus vectors + document_chunks on hard
                            delete
  knowledge_text_service  — resolve KnowledgeDocument → plain text
                            (fast path: document_chunks; slow path:
                            re-parse from S3)
"""
