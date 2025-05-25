# routers/remove_member.py

import logging
import requests
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models, schemas, crud
from database import SessionLocal
from overleaf_utils import (
    get_tokens,
    get_captcha_token,
    perform_login,
    refresh_session,
    get_new_csrf
)

router = APIRouter(prefix="/api/v1/member", tags=["members"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/remove", response_model=schemas.RemoveMemberResponse)
async def remove_member(
    body: schemas.MemberEmailRequest,
    db: Session = Depends(get_db)
):
    # 1. 查最新有效邀请记录
    invite = (
        db.query(models.Invite)
          .filter(
              models.Invite.email == body.email,
              models.Invite.email_id.isnot(None),
              models.Invite.cleaned.is_(False)  # 只处理未清理的
          )
          .order_by(models.Invite.created_at.desc())
          .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="未找到有效邀请记录")

    # 2. 加载邀请所用账号
    acct = db.get(models.Account, invite.account_id)
    if not acct:
        raise HTTPException(status_code=500, detail="找不到邀请账户信息")

    session = requests.Session()
    new_sess = acct.session_cookie
    new_csrf = acct.csrf_token

    # 3. 尝试复用已有的 session/CSRF
    if new_sess and new_csrf:
        session.cookies.set(
            "overleaf_session2", new_sess,
            domain=".overleaf.com", path="/"
        )
        try:
            new_sess = await asyncio.to_thread(refresh_session, session, new_csrf)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        except Exception:
            new_sess = new_csrf = None

    # 4. 如复用失败，完整登录流程
    if not (new_sess and new_csrf):
        csrf0, sess0 = await get_tokens()
        captcha = get_captcha_token()
        session = await asyncio.to_thread(
            perform_login, csrf0, sess0,
            acct.email, acct.password, captcha
        )
        new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
        new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)

    # 5. 更新数据库中的 token
    crud.update_account_tokens(db, acct, new_csrf, new_sess)

    # 6. 调用 Overleaf API 删除组员
    url = f"https://www.overleaf.com/manage/groups/{acct.group_id}/user/{invite.email_id}"
    resp = session.delete(url, headers={
        "Accept": "application/json",
        "x-csrf-token": new_csrf,
        "Referer": f"https://www.overleaf.com/manage/groups/{acct.group_id}/members",
        "User-Agent": "Mozilla/5.0"
    })
    if resp.status_code not in (200, 204):
        logging.error(f"删除成员失败: {resp.status_code} {resp.text}")
        raise HTTPException(status_code=resp.status_code, detail=f"删除失败: {resp.text}")

    # 7. 本地库中将 invites_sent 减 1
    if acct.invites_sent > 0:
        acct.invites_sent -= 1
        db.commit()
        db.refresh(acct)

    # —— 新增：标记这条邀请记录已经清理 —— #
    invite.cleaned = True
    db.add(invite)
    db.commit()

    return schemas.RemoveMemberResponse(
        status="success",
        detail="成员已删除"
    )
