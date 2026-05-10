"""
Full rebuild script: Clean → Rebuild Milvus → Re-ingest → Build Dataset → Run Evaluation

Usage:
    python scripts/_run_full_rebuild.py
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Bootstrap
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv
load_dotenv()

from app.core.config import settings
from app.core.hf_runtime import prepare_hf_runtime

prepare_hf_runtime()


# ─────────────────────────────────────────────────────────────────────────────
# Step 0: Check for residual files and clean up
# ─────────────────────────────────────────────────────────────────────────────

def step0_cleanup():
    print("=" * 60)
    print("  Step 0: Cleanup residual files")
    print("=" * 60)

    # Remove old golden dataset
    old_dataset = PROJECT_ROOT / "evaluation" / "golden_dataset.jsonl"
    if old_dataset.exists():
        old_dataset.unlink()
        print(f"  ✓ Removed old golden_dataset: {old_dataset}")

    # Remove old report dirs
    reports_dir = Path(settings.EVAL_DIR) / "reports"
    if reports_dir.exists():
        import shutil
        for child in reports_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
                print(f"  ✓ Removed old report: {child.name}")

    # Remove old nvidia eval files
    eval_dir = Path(settings.EVAL_DIR)
    for f in eval_dir.glob("nvidia_model_matrix_*"):
        f.unlink()
        print(f"  ✓ Removed residual file: {f.name}")

    print("  Cleanup complete.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Rebuild Milvus Collection (drop old, create with new dim=1024)
# ─────────────────────────────────────────────────────────────────────────────

def step1_rebuild_milvus():
    print("=" * 60)
    print("  Step 1: Rebuild Milvus Collection")
    print("=" * 60)
    print(f"  Collection: {settings.MILVUS_COLLECTION}")
    print(f"  New dimension: {settings.EMBEDDING_DIM}")

    from pymilvus import connections, utility

    # Connect
    uri = settings.MILVUS_URI
    host = uri.replace("http://", "").split(":")[0]
    port = uri.replace("http://", "").split(":")[-1]
    connections.connect(alias="default", host=host, port=port)

    # Drop old RAG collection
    for coll_name in [settings.MILVUS_COLLECTION]:
        if utility.has_collection(coll_name):
            utility.drop_collection(coll_name)
            print(f"  ✓ Dropped collection: {coll_name}")
        else:
            print(f"  ○ Collection not found: {coll_name}")

    connections.disconnect("default")
    print("  Milvus rebuild complete.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Clear PostgreSQL docstore and re-ingest all docs
# ─────────────────────────────────────────────────────────────────────────────

async def step2_reingest():
    print("=" * 60)
    print("  Step 2: Clear docstore and re-ingest documents")
    print("=" * 60)

    # Clear docstore
    import sqlalchemy
    engine = sqlalchemy.create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        # Check what tables exist
        result = conn.execute(sqlalchemy.text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ))
        tables = [row[0] for row in result]
        print(f"  Existing tables: {tables}")

        # Clear docstore data
        for tbl in ["data_docstore", "data_index_store", "data_graph_store"]:
            if tbl in tables:
                conn.execute(sqlalchemy.text(f"DELETE FROM {tbl}"))
                print(f"  ✓ Cleared table: {tbl}")
        conn.commit()
    engine.dispose()

    # Initialize embedding model
    from app.rag.embeddings import init_rag_settings
    init_rag_settings()

    # Find all interview QA files
    upload_dir = Path(settings.STORAGE_DIR) / "uploads"
    qa_files = []
    if upload_dir.exists():
        for f in upload_dir.rglob("*"):
            if f.suffix.lower() in (".pdf", ".md", ".txt"):
                qa_files.append(f)

    # Also check for known QA files in other locations
    data_dir = PROJECT_ROOT / "data"
    for f in data_dir.rglob("*.pdf"):
        if f not in qa_files:
            qa_files.append(f)

    if not qa_files:
        print("  ⚠ No document files found. Will ingest via API later.")
        print("  Re-ingest skipped.\n")
        return

    # Ingest each file
    from app.rag.ingestion import ingest_document
    user_id = "eval_user_a"
    total_chunks = 0

    for idx, fpath in enumerate(qa_files, 1):
        print(f"  [{idx}/{len(qa_files)}] Ingesting: {fpath.name}")
        try:
            result = await ingest_document(
                file_path=str(fpath),
                source_type="interview_qa",
                user_id=user_id,
            )
            chunks = result.get("chunk_count", 0)
            total_chunks += chunks
            print(f"    → {chunks} chunks")
        except Exception as e:
            print(f"    ✗ Failed: {e}")

    print(f"  Total chunks ingested: {total_chunks}")
    print("  Re-ingest complete.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Build golden dataset from docstore
# ─────────────────────────────────────────────────────────────────────────────

def step3_build_dataset():
    print("=" * 60)
    print("  Step 3: Build golden dataset from docstore")
    print("=" * 60)

    import sqlalchemy
    engine = sqlalchemy.create_engine(settings.DATABASE_URL)

    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(
            "SELECT key, value FROM data_docstore WHERE namespace = 'docstore/data'"
        ))
        rows = result.fetchall()

    engine.dispose()
    print(f"  Found {len(rows)} nodes in docstore")

    # Parse Q&A pairs from chunks
    # The chunks come from interview QA PDFs parsed via LlamaParse to markdown
    # We need to find complete Q&A pairs
    qa_pairs = []
    for node_key, node_value_raw in rows:
        try:
            if isinstance(node_value_raw, str):
                node_value = json.loads(node_value_raw)
            else:
                node_value = node_value_raw

            # Navigate nested structure: {"__data__": {"id_": ..., "text": ..., "metadata": ...}}
            node_data = node_value.get("__data__", node_value)
            node_id = node_data.get("id_", node_key)

            text = node_data.get("text", "")
            metadata = node_data.get("metadata", {})
            user_id = metadata.get("user_id", "eval_user_a")
            source_type = metadata.get("source_type", "interview_qa")
            file_name = metadata.get("file_name", "")

            if not text or len(text.strip()) < 30:
                continue

            # Only use interview_qa documents
            if source_type != "interview_qa":
                continue

            # Try to extract Q&A structure from the chunk text
            # Many chunks contain a question heading followed by answer text
            lines = text.strip().split("\n")

            # Heuristic 1: Find question-like lines (starting with question words or ending with ?)
            # and use the rest as answer
            question = None
            answer_lines = []

            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue

                # Check if this line looks like a question
                is_question = (
                    stripped.endswith("？") or
                    stripped.endswith("?") or
                    stripped.startswith("##") or
                    any(stripped.startswith(kw) for kw in [
                        "什么是", "如何", "怎么", "为什么", "请",
                        "说明", "解释", "描述", "介绍", "你",
                        "What", "How", "Why", "When", "Explain",
                    ])
                )

                if is_question and question is None and len(stripped) > 5:
                    question = stripped.lstrip("#").strip()
                    answer_lines = lines[i + 1:]
                    break

            if question and answer_lines:
                answer = "\n".join(answer_lines).strip()
                if len(answer) > 20:
                    qa_pairs.append({
                        "query": question,
                        "reference_answer": answer,
                        "user_id": user_id,
                        "source_type": source_type,
                        "file_name": file_name,
                        "node_id": node_id,
                    })
            elif len(text.strip()) > 50:
                # Use the first meaningful line as query, rest as answer
                first_line = None
                rest_lines = []
                for i, line in enumerate(lines):
                    if line.strip() and len(line.strip()) > 3:
                        if first_line is None:
                            first_line = line.strip().lstrip("#").strip()
                            rest_lines = lines[i + 1:]
                            break

                if first_line and rest_lines:
                    answer = "\n".join(rest_lines).strip()
                    if len(answer) > 20 and len(first_line) > 5:
                        qa_pairs.append({
                            "query": first_line,
                            "reference_answer": answer,
                            "user_id": user_id,
                            "source_type": source_type,
                            "file_name": file_name,
                            "node_id": node_id,
                        })

        except Exception as e:
            continue

    # Deduplicate by query
    seen_queries = set()
    unique_pairs = []
    for pair in qa_pairs:
        q_key = pair["query"].strip().lower()[:80]
        if q_key not in seen_queries:
            seen_queries.add(q_key)
            unique_pairs.append(pair)

    print(f"  Extracted {len(unique_pairs)} unique Q&A pairs")

    # Quality filter: ensure both Q and A have substance
    quality_pairs = []
    for pair in unique_pairs:
        q = pair["query"]
        a = pair["reference_answer"]
        # Filter out fragment-like queries (too short or just code/numbers)
        if len(q) < 6:
            continue
        if len(a) < 30:
            continue
        quality_pairs.append(pair)

    print(f"  After quality filter: {len(quality_pairs)} pairs")

    # Split: 301 for retrieval (all layers), 100 for generation
    # Assign layer tags
    dataset_rows = []

    # Use all for retrieval
    for idx, pair in enumerate(quality_pairs):
        layer = "all" if idx < min(100, len(quality_pairs)) else "retrieval"
        dataset_rows.append({
            "id": f"{layer}-{idx + 1:03d}",
            "layer": layer,
            "query": pair["query"],
            "reference_answer": pair["reference_answer"],
            "user_id": pair["user_id"],
            "source_type": pair["source_type"],
            "tags": ["knowledge", "qa"],
            "source_file": pair["file_name"],
        })

    # Write dataset
    output_path = PROJECT_ROOT / "evaluation" / "golden_dataset.jsonl"
    with output_path.open("w", encoding="utf-8") as f:
        for row in dataset_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"  ✓ Written {len(dataset_rows)} rows to {output_path}")
    print(f"    - 'all' layer (retrieval + generation): {sum(1 for r in dataset_rows if r['layer'] == 'all')}")
    print(f"    - 'retrieval' only: {sum(1 for r in dataset_rows if r['layer'] == 'retrieval')}")
    print("  Dataset build complete.\n")
    return len(dataset_rows)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print("\n" + "=" * 60)
    print("  FULL REBUILD: BGE-M3 Migration")
    print(f"  Embedding: {settings.EMBEDDING_MODEL_ID}")
    print(f"  Dimension: {settings.EMBEDDING_DIM}")
    print("=" * 60 + "\n")

    step0_cleanup()
    step1_rebuild_milvus()
    await step2_reingest()
    n_rows = step3_build_dataset()

    if not n_rows:
        print("⚠ No dataset rows generated. Check if documents were ingested.")
        return

    print("\n" + "=" * 60)
    print("  Rebuild complete! Next step:")
    print("  python -m evaluation.eval_runner --all --report")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
