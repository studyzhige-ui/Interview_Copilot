"""Memory item CRUD endpoints (list / get / delete)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.memory import MemoryItem
from app.models.user import User
from app.services.memory.retrieval_service import memory_retrieval_service

router = APIRouter(tags=["chat"])


@router.get("/memory/items")
async def list_memory_items(current_user: User = Depends(get_current_user)):
    items = await memory_retrieval_service.get_memory_index(current_user.username)
    return {"status": "success", "items": items, "total": len(items)}


@router.get("/memory/items/{memory_id}")
def get_memory_item(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(MemoryItem)
        .filter(MemoryItem.id == memory_id, MemoryItem.user_id == current_user.username)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Memory item not found")
    return {
        "status": "success",
        "item": {
            "id": row.id,
            "type": row.type,
            "scope": row.scope,
            "description": row.description,
            "normalized_key": row.normalized_key,
            "content": row.content,
            "confidence": row.confidence or 0.0,
            "importance": row.importance or 0.0,
            "source_session_id": row.source_session_id,
            "last_evidence_seq": row.last_evidence_seq,
            "recall_count": row.recall_count or 0,
            "last_accessed_at": (
                row.last_accessed_at.isoformat() if row.last_accessed_at else None
            ),
            "embedding_status": row.embedding_status,
            "embedding_model": row.embedding_model,
            "embedded_at": row.embedded_at.isoformat() if row.embedded_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        },
    }


@router.delete("/memory/items/{memory_id}")
def delete_memory_item(
    memory_id: str,
    current_user: User = Depends(get_current_user),
):
    success = memory_retrieval_service.delete_memory(memory_id, current_user.username)
    if not success:
        raise HTTPException(status_code=404, detail="Memory item not found or access denied")
    return {"status": "success", "message": f"Memory {memory_id} deleted"}
