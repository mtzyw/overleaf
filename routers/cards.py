# routers/cards.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Union, Optional

import models, crud, schemas
from database import SessionLocal

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("", response_model=List[schemas.CardOut])
def list_cards(
    page: int = 1,
    size: int = 50,
    used: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Card)
    if used is not None:
        query = query.filter(models.Card.used == used)
    cards = query.offset((page-1)*size).limit(size).all()
    return cards

@router.post("/add", response_model=List[schemas.CardOut])
def add_cards(
    data: Union[schemas.CardCreate, List[schemas.CardCreate]],
    db: Session = Depends(get_db)
):
    """
    批量或单个新增卡密。如果某个 code 已存在，则跳过。
    返回所有新创建的 Card 对象列表。
    """
    items = data if isinstance(data, list) else [data]
    created: List[models.Card] = []
    for item in items:
        # 先检查是否已存在
        existing = db.query(models.Card).filter(models.Card.code == item.code).first()
        if existing:
            # 跳过已存在的 code
            continue
        # 不存在则创建
        card = crud.create_card(db, item.code, item.days)
        created.append(card)
    return created

@router.post("/delete")
def delete_card(
    body: schemas.CardDeleteRequest,
    db: Session = Depends(get_db)
):
    success = crud.delete_card(db, body.code)
    if not success:
        raise HTTPException(status_code=404, detail="卡密不存在")
    return {"success": True}
