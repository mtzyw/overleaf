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

    session = requests.Session()
    need_login = not (acct.session_cookie and acct.csrf_token)
    if not need_login:
        session.cookies.set("overleaf_session2", acct.session_cookie,
                            domain=".overleaf.com", path="/")
        try:
            new_sess = await refresh_session(session, acct.csrf_token)
            new_csrf = await get_new_csrf(session, acct.group_id)
        except Exception:
            need_login = True
    if need_login:
        csrf0, sess0 = await get_tokens()
        captcha = get_captcha_token()
        session = perform_login(csrf0, sess0, acct.email, acct.password, captcha)
        new_sess = refresh_session(session, csrf0)
        new_csrf = get_new_csrf(session, acct.group_id)

    return crud.update_account_tokens(db, acct, new_csrf, new_sess)
