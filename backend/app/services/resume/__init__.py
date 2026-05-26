"""Resume parsing + vectorization services.

  resume_service          — parse resume → 4 typed sections (summary /
                            project / education / skill), persist to
                            DB, optional vectorize
  resume_vector_service   — Milvus vector store for ResumeSection
                            (lazy singleton with double-checked lock)
"""
