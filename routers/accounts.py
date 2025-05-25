# routers/accounts.py

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
    """
    创建新账号。请求体需包含 AccountCreate 模型字段。
    """
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
    import requests

    # 初始化，避免未赋值引用
    new_sess = acct.session_cookie if acct.session_cookie else None
    new_csrf = acct.csrf_token if acct.csrf_token else None
    session = requests.Session()
    need_login = not (new_sess and new_csrf)

    if not need_login:
        session.cookies.set(
            "overleaf_session2", new_sess,
            domain=".overleaf.com", path="/"
        )
        try:
            # 第一次尝试刷新
            refreshed = await refresh_session(session, new_csrf)
            new_sess = refreshed
            new_csrf = await get_new_csrf(session, acct.group_id)
        except Exception:
            need_login = True

    if need_login:
        # 重新登录获取 token
        csrf0, sess0 = await get_tokens()
        captcha = get_captcha_token()
        session = perform_login(csrf0, sess0, acct.email, acct.password, captcha)
        new_sess = refresh_session(session, csrf0)
        new_csrf = get_new_csrf(session, acct.group_id)

    # 更新数据库并返回最新信息
    return crud.update_account_tokens(db, acct, new_csrf, new_sess)