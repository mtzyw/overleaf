# routers/update_email_id.py

import re
import json
import html
import requests
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models, schemas, crud
from database import SessionLocal
from overleaf_utils import get_tokens, get_captcha_token, perform_login, refresh_session, get_new_csrf

router = APIRouter(prefix="/api/v1/email_ids", tags=["members"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/update", response_model=schemas.UpdateEmailIdsResponse)
async def update_email_ids(
    body: schemas.LeaderEmailRequest,
    db: Session = Depends(get_db)
):
    acct = db.query(models.Account).filter(models.Account.email == body.leader_email).first()
    if not acct:
        raise HTTPException(status_code=404, detail="组长账号不存在")

    session = requests.Session()
    need_login = not (acct.session_cookie and acct.csrf_token)
    if not need_login:
        session.cookies.set("overleaf_session2", acct.session_cookie,
                            domain=".overleaf.com", path="/")
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
        crud.update_account_tokens(db, acct, new_csrf, new_sess)

    url = f"https://www.overleaf.com/manage/groups/{acct.group_id}/members"
    resp = session.get(url, headers={
        "Accept": "text/html",
        "Referer": "https://www.overleaf.com/project",
        "User-Agent": "Mozilla/5.0",
    })
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="获取成员列表失败")

    m = re.search(r'<meta\s+name="ol-users"\s+data-type="json"\s+content="([^"]+)"', resp.text)
    if not m:
        raise HTTPException(status_code=500, detail="未找到 ol-users 元数据标签")
    raw = html.unescape(m.group(1))
    users = json.loads(raw)

    updated = 0
    for u in users:
        email = u.get("email")
        uid = u.get("_id")
        if not email or not uid:
            continue
        invites_qs = db.query(models.Invite).filter(models.Invite.email == email).all()
        for inv in invites_qs:
            if inv.email_id != uid:
                inv.email_id = uid
                updated += 1

    db.commit()
    return schemas.UpdateEmailIdsResponse(
        leader_email=body.leader_email,
        total_members=len(users),
        updated_invites=updated
    )
