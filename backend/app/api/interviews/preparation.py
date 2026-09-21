"""Preparation reads use the same application operation as Copilot."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.core.rate_limit import limiter, RATE_DEFAULT
from app.db.database import get_db
from app.models.user import User
from app.career.application.resumes.resume_artifact_service import (
    ResumeArtifactNotFoundError,
)
from app.interviews.application.preparation import (
    build_preparation,
    PreparationSourceChanged,
)
from app.schemas.mock_preparation import MockPreparationRequest
from app.schemas.preparation import PreparationBrief

router = APIRouter()


@router.post("/mock-interviews/preparation", response_model=PreparationBrief)
@limiter.limit(RATE_DEFAULT)
def preparation(
    request: Request,
    response: Response,
    body: MockPreparationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return build_preparation(db, user_pk=current_user.id, command=body)
    except ResumeArtifactNotFoundError as exc:
        raise HTTPException(404, "简历不存在") from exc
    except PreparationSourceChanged as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
