# routers/invite.py

import re
import html
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import requests

import models, crud, schemas
from database import SessionLocal
from overleaf_utils import (
    get_tokens,
    get_captcha_token,
    perform_login,
    refresh_session,
    get_new_csrf
)

router = APIRouter(
    prefix="/api/v1/invite",
    tags=["invites"]
)

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
async def invite(
    req: schemas.InviteRequest,
    db: Session = Depends(get_db)
):
    # 1. 验证卡密 & 选账号
    card = crud.get_card(db, req.card)
    if not card:
        raise HTTPException(status_code=400, detail="无效或已使用的卡密")
    acct = crud.get_available_account(db)
    if not acct:
        raise HTTPException(status_code=400, detail="无可用账号")

    # 2. 计算时间戳 & ISO 格式
    now = datetime.now()
    expire = now + timedelta(days=card.days)
    now_ts = int(now.timestamp())
    expire_ts = int(expire.timestamp())
    expires_iso = expire.isoformat()

    # 3. 尝试复用旧 session/CSRF
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
            result = await asyncio.to_thread(
                send_invite, session, new_csrf, acct.group_id, req.email, expires_iso
            )
            reuse_ok = True
        except Exception:
            reuse_ok = False

    # 4. 如复用失败，则完整登录流程
    if not reuse_ok:
        csrf0, sess0 = await get_tokens()
        captcha = get_captcha_token()
        session = await asyncio.to_thread(
            perform_login, csrf0, sess0, acct.email, acct.password, captcha
        )
        new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
        new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        result = await asyncio.to_thread(
            send_invite, session, new_csrf, acct.group_id, req.email, expires_iso
        )
        crud.update_account_tokens(db, acct, new_csrf, new_sess)

    # 5. 记录本地数据库 & 返回
    crud.increment_invites(db, acct)
    crud.mark_card_used(db, card)
    crud.create_invite_record(db, acct, req.email, expire_ts, True, result, card)

    return schemas.InviteResponse(
        success=True,
        result=result,
        sent_ts=now_ts,
        expires_ts=expire_ts
    )


@router.get("/records", response_model=List[schemas.InviteRecord])
def list_invites(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1),
    email: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    列出邀请记录，可按被邀请人邮箱过滤。
    """
    q = db.query(models.Invite)
    if email:
        q = q.filter(models.Invite.email == email)
    invites = q.order_by(models.Invite.created_at.desc()) \
               .offset((page - 1) * size) \
               .limit(size) \
               .all()
    return invites
