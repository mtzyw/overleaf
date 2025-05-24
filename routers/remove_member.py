# routers/remove_member.py

import requests
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models, schemas, crud
from database import SessionLocal
from overleaf_utils import get_tokens, get_captcha_token, perform_login, refresh_session, get_new_csrf

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
    # 找到最新的一条有效邀请记录
    invite = (
        db.query(models.Invite)
          .filter(
              models.Invite.email == body.email,
              models.Invite.email_id.isnot(None)
          )
          .order_by(models.Invite.created_at.desc())
          .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="未找到有效邀请记录")

    member_id = invite.email_id
    acct = db.query(models.Account).get(invite.account_id)
    if not acct:
        raise HTTPException(status_code=500, detail="找不到邀请账户信息")

    # 复用 Session 登录 Overleaf
    session = requests.Session()
    need_login = not (acct.session_cookie and acct.csrf_token)
    if not need_login:
        session.cookies.set(
            "overleaf_session2", acct.session_cookie,
            domain=".overleaf.com", path="/"
        )
        try:
            new_sess = await asyncio.to_thread(refresh_session, session, acct.csrf_token)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        except Exception:
            need_login = True

    if need_login:
        csrf0, sess0 = await get_tokens()
        captcha = get_captcha_token()
        session = await asyncio.to_thread(
            perform_login, csrf0, sess0,
            acct.email, acct.password, captcha
        )
        new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
        new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        # 更新本地账户的最新 token
        crud.update_account_tokens(db, acct, new_csrf, new_sess)

    # 调用 Overleaf API 删除成员
    url = f"https://www.overleaf.com/manage/groups/{acct.group_id}/user/{member_id}"
    resp = session.delete(url, headers={
        "Accept": "application/json",
        "x-csrf-token": new_csrf,
        "Referer": f"https://www.overleaf.com/manage/groups/{acct.group_id}/members",
        "User-Agent": "Mozilla/5.0"
    })
    if resp.status_code not in (200, 204):
        raise HTTPException(status_code=resp.status_code, detail=f"删除失败: {resp.text}")

    # —— 在本地数据库里把 invites_sent 减 1 并提交 —— #
    if acct.invites_sent and acct.invites_sent > 0:
        acct.invites_sent -= 1
        db.add(acct)
        db.commit()

    return schemas.RemoveMemberResponse(
        status="success",
        detail=resp.text or "成员已删除"
    )
