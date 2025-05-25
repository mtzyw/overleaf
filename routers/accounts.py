# routers/accounts.py

import asyncio
import requests
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Optional

import crud, models, schemas
from database import SessionLocal

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("", response_model=List[schemas.AccountOut])
def list_accounts(
    page: int = 1,
    size: int = 20,
    email: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Account)
    if email:
        query = query.filter(models.Account.email == email)
    return query.offset((page-1)*size).limit(size).all()

@router.post("/add", response_model=schemas.AccountOut)
def add_account(
    data: schemas.AccountCreate = Body(...),
    db: Session = Depends(get_db)
):
    return crud.create_account(
        db,
        email=data.email,
        password=data.password,
        group_id=data.group_id,
        max_invites=data.max_invites
    )

@router.post("/delete")
def delete_account(
    body: schemas.EmailRequest = Body(...),
    db: Session = Depends(get_db)
):
    success = crud.delete_account(db, body.email)
    if not success:
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"success": True}

@router.post("/refresh", response_model=schemas.AccountOut)
async def refresh_account(
    body: schemas.EmailRequest = Body(...),
    db: Session = Depends(get_db)
):
    acct = db.query(models.Account).filter(models.Account.email == body.email).first()
    if not acct:
        raise HTTPException(status_code=404, detail="账号不存在")

    from overleaf_utils import get_tokens, get_captcha_token, perform_login, refresh_session, get_new_csrf

    # 初始带上旧 token（可能为 None）
    new_sess = acct.session_cookie
    new_csrf = acct.csrf_token
    session = requests.Session()
    need_login = not (new_sess and new_csrf)

    if not need_login:
        session.cookies.set("overleaf_session2", new_sess, domain=".overleaf.com", path="/")
        try:
            # 刷新 session & csrf 都放到线程池里跑
            new_sess = await asyncio.to_thread(refresh_session, session, new_csrf)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        except Exception:
            need_login = True

    if need_login:
        # 完整登录流程，也放到线程里
        csrf0, sess0 = await get_tokens()
        captcha = get_captcha_token()
        session = await asyncio.to_thread(perform_login, csrf0, sess0, acct.email, acct.password, captcha)
        new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
        new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)

    # 更新数据库并返回
    return crud.update_account_tokens(db, acct, new_csrf, new_sess)
