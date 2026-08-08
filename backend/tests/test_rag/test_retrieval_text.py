from app.rag.retrieval_text import build_retrieval_text


def test_build_retrieval_text_adds_stable_structural_context() -> None:
    result = build_retrieval_text(
        "The worker acknowledges the message.",
        document_title="Celery Tasks",
        heading_path=["Tasks", "Acknowledgements"],
        section_title="Acknowledgements",
    )

    assert result == (
        "Document: Celery Tasks\n"
        "Section: Tasks > Acknowledgements\n"
        "The worker acknowledges the message."
    )


def test_build_retrieval_text_keeps_plain_chunks_unchanged() -> None:
    assert build_retrieval_text("plain fact") == "plain fact"
