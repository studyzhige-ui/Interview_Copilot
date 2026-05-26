"""Knowledge document lifecycle services.

  knowledge_service       — CRUD for KnowledgeDocument rows; deletes
                            Milvus vectors + docstore entries on hard
                            delete
  knowledge_text_service  — resolve KnowledgeDocument → plain text
                            (fast path: docstore; slow path: re-parse
                            from S3)
"""
