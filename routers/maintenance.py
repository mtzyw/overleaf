from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import crud, schemas
from database import SessionLocal
from invite_status_manager import InviteStatusManager

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
def cleanup_expired(
    delete_records: bool = Query(True, description="是否真正删除记录（默认True）"),
    limit: int = Query(100, description="单次处理的最大数量"),
    db: Session = Depends(get_db)
):
    """
    清理所有已过期且未清理的邀请记录
    
    - delete_records=True: 真正删除记录（推荐）
    - delete_records=False: 只标记为已清理（兼容旧模式）
    """
    stats = InviteStatusManager.batch_cleanup_expired(db, limit=limit, delete_records=delete_records)
    
    # 兼容旧的响应格式
    cleaned = stats["deleted_records"] + stats["marked_processed"]
    
    return {
        "cleaned": cleaned,
        "stats": stats
    }
