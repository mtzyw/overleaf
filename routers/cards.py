# routers/cards.py

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List

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
    used: bool | None = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Card)
    if used is not None:
        query = query.filter(models.Card.used == used)
    return query.offset((page-1)*size).limit(size).all()

@router.post("/add", response_model=List[schemas.CardOut])
def add_cards(
    data: List[schemas.CardCreate] = Body(..., example=[{"code":"abc12","days":7}]),
    db: Session = Depends(get_db)
):
    """
    批量新增卡密。接收一个数组，每项包含 code 和 days。
    如果某个 code 已存在，则跳过。
    返回所有新创建的 Card 对象列表。
    """
    created: list[models.Card] = []
    for item in data:
        if not db.query(models.Card).filter(models.Card.code == item.code).first():
            created.append(crud.create_card(db, item.code, item.days))
    return created

@router.post("/delete")
def delete_card(
    body: schemas.CardDeleteRequest = Body(...),
    db: Session = Depends(get_db)
):
    success = crud.delete_card(db, body.code)
    if not success:
        raise HTTPException(status_code=404, detail="卡密不存在")
    return {"success": True}
