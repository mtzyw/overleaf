# routers/maintenance.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import crud, schemas
from database import SessionLocal

router = APIRouter(
    prefix="/api/v1/maintenance",
    tags=["maintenance"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/cleanup_expired", response_model=schemas.CleanupResponse)
def cleanup_expired(db: Session = Depends(get_db)):
    """
    清理所有已过期且未清理的邀请记录，
    返回本次成功清理的总数。
    """
    cleaned = crud.clean_expired_invites(db)
    return {"cleaned": cleaned}
