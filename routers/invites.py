import html, json, asyncio, requests
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import models, crud, schemas
from database import SessionLocal
from overleaf_utils import (
    get_tokens, get_captcha_token,
    perform_login, refresh_session, get_new_csrf
)

router = APIRouter(prefix="/api/v1/invite", tags=["invites"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def send_invite(
    session: requests.Session,
    csrf: str,
    group_id: str,
    email: str,
    expires_iso: str
) -> dict:
    resp = session.post(
        f"https://www.overleaf.com/manage/groups/{group_id}/invites",
        json={"email": email, "expiresAt": expires_iso},
        headers={
            "x-csrf-token": csrf,
            "Accept": "application/json",
            "Referer": f"https://www.overleaf.com/manage/groups/{group_id}/members",
            "User-Agent": "Mozilla/5.0"
        }
    )
    if resp.status_code != 200:
        raise RuntimeError(f"邀请失败: {resp.status_code} {resp.text}")
    return resp.json()

@router.post("", response_model=schemas.InviteResponse)
async def invite(req: schemas.InviteRequest, db: Session = Depends(get_db)):
    # 1. 验证卡密 & 选账号
    card = crud.get_card(db, req.card)
    if not card:
        raise HTTPException(400, "无效或已使用的卡密")
    acct = crud.get_available_account(db)
    if not acct:
        raise HTTPException(400, "无可用账号")

    # 2. 计算时间戳 & ISO
    now = datetime.now()
    expires = now + timedelta(days=card.days)
    now_ts = int(now.timestamp())
    expires_ts = int(expires.timestamp())
    expires_iso = expires.isoformat()

    # 3. 尝试复用 session/CSRF
    reuse_ok = False
    session = requests.Session()
    if acct.session_cookie and acct.csrf_token:
        session.cookies.set(
            "overleaf_session2", acct.session_cookie,
            domain=".overleaf.com", path="/"
        )
        try:
            new_sess = await asyncio.to_thread(refresh_session, session, acct.csrf_token)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
            result   = await asyncio.to_thread(
                send_invite, session, new_csrf, acct.group_id, req.email, expires_iso
            )
            reuse_ok = True
        except Exception:
            reuse_ok = False

    # 4. 如果复用失败，完整登录
    if not reuse_ok:
        csrf0, sess0 = await get_tokens()
        captcha     = get_captcha_token()
        session     = await asyncio.to_thread(
            perform_login, csrf0, sess0, acct.email, acct.password, captcha
        )
        new_sess    = await asyncio.to_thread(refresh_session, session, csrf0)
        new_csrf    = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        result      = await asyncio.to_thread(
            send_invite, session, new_csrf, acct.group_id, req.email, expires_iso
        )
        crud.update_account_tokens(db, acct, new_csrf, new_sess)

    # 5. 本地更新：increment & mark_card_used
    crud.increment_invites(db, acct)
    crud.mark_card_used(db, card)

    # 6. 如果已有该邮箱的记录，续期；否则新建
    last = (
        db.query(models.Invite)
          .filter(models.Invite.email == req.email)
          .order_by(models.Invite.created_at.desc())
          .first()
    )
    if last:
        crud.update_invite_expiry(db, last, expires_ts, result)
    else:
        crud.create_invite_record(db, acct, req.email, expires_ts, True, result, card)

    return schemas.InviteResponse(
        success    = True,
        result     = result,
        sent_ts    = now_ts,
        expires_ts = expires_ts
    )

@router.get("/records", response_model=List[schemas.InviteRecord])
def list_invites(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1),
    email: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    q = db.query(models.Invite)
    if email:
        q = q.filter(models.Invite.email == email)
    return (
        q.order_by(models.Invite.created_at.desc())
         .offset((page - 1) * size)
         .limit(size)
         .all()
    )
