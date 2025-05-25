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
from overleaf_utils import (
    get_tokens,
    get_captcha_token,
    perform_login,
    refresh_session,
    get_new_csrf
)

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
    # 1. 找到组长账号
    acct = db.query(models.Account).filter_by(email=body.leader_email).first()
    if not acct:
        raise HTTPException(status_code=404, detail="组长账号不存在")

    session = requests.Session()
    new_sess = acct.session_cookie
    new_csrf = acct.csrf_token

    # 2. 尝试复用并刷新（如果已有 token）
    if new_sess and new_csrf:
        session.cookies.set("overleaf_session2", new_sess,
                            domain=".overleaf.com", path="/")
        try:
            new_sess = await asyncio.to_thread(refresh_session, session, new_csrf)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        except Exception:
            new_sess = new_csrf = None

    # 3. 如复用失败，执行完整登录流程
    if not (new_sess and new_csrf):
        csrf0, sess0 = await get_tokens()
        captcha = get_captcha_token()
        session = await asyncio.to_thread(
            perform_login, csrf0, sess0,
            acct.email, acct.password, captcha
        )
        new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
        new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)

    # 4. 更新数据库里的最新 token
    crud.update_account_tokens(db, acct, new_csrf, new_sess)

    # 5. 拉取 Overleaf 成员列表页
    url = f"https://www.overleaf.com/manage/groups/{acct.group_id}/members"
    resp = session.get(url, headers={
        "Accept": "text/html",
        "Referer": "https://www.overleaf.com/project",
        "User-Agent": "Mozilla/5.0",
    })
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="获取成员列表失败")

    # 6. 从页面 <meta name="ol-users"> 中解析 JSON
    m = re.search(r'<meta\s+name="ol-users"\s+data-type="json"\s+content="([^"]+)"', resp.text)
    if not m:
        raise HTTPException(status_code=500, detail="未找到 ol-users 元数据标签")
    users = json.loads(html.unescape(m.group(1)))

    # 7. 更新本地 Invite 记录中的 email_id
    updated = 0
    for u in users:
        email = u.get("email")
        uid   = u.get("_id")
        if not email or not uid:
            continue
        # 查询所有该 email 的邀请记录
        for inv in db.query(models.Invite).filter_by(email=email).all():
            if inv.email_id != uid:
                inv.email_id = uid
                updated += 1

    db.commit()

    return schemas.UpdateEmailIdsResponse(
        leader_email=body.leader_email,
        total_members=len(users),
        updated_invites=updated
    )
