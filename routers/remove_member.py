import logging
import requests
import asyncio
import json  # 新增：用于处理 JSON 响应
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

# 定义一个日志器 (如果此文件还没有)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # 可以根据需要调整日志级别
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


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
    """
    通过 email_id 从 Overleaf 组中移除已接受邀请的成员。
    """
    # 1. 查最新有效邀请记录 (要求 email_id 存在且未清理)
    invite = (
        db.query(models.Invite)
        .filter(
            models.Invite.email == body.email,
            models.Invite.email_id.isnot(None),  # 关键：要求 email_id 存在
            models.Invite.cleaned.is_(False)  # 只处理未清理的
        )
        .order_by(models.Invite.created_at.desc())
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="未找到有效且已接受的邀请记录")

    # 2. 加载邀请所用账号 (与 revoke_unaccepted_invite 相同)
    acct = db.get(models.Account, invite.account_id)
    if not acct:
        raise HTTPException(status_code=500, detail="找不到邀请账户信息")

    session = requests.Session()
    new_sess = acct.session_cookie
    new_csrf = acct.csrf_token

    # 3. 尝试复用已有的 session/CSRF (与 revoke_unaccepted_invite 相同)
    if new_sess and new_csrf:
        session.cookies.set(
            "overleaf_session2", new_sess,
            domain=".overleaf.com", path="/"
        )
        try:
            new_sess = await asyncio.to_thread(refresh_session, session, new_csrf)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        except Exception as e:
            logger.warning(f"账号 {acct.email} session/CSRF 刷新失败: {e}. 将尝试完整登录。")
            new_sess = new_csrf = None

    # 4. 如复用失败，完整登录流程 (与 revoke_unaccepted_invite 相同)
    if not (new_sess and new_csrf):
        try:
            csrf0, sess0 = await get_tokens()
            captcha = get_captcha_token()
            session = await asyncio.to_thread(
                perform_login, csrf0, sess0,
                acct.email, acct.password, captcha
            )
            new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        except Exception as e:
            logger.error(f"账号 {acct.email} 完整登录失败: {e}")
            raise HTTPException(status_code=500, detail=f"登录 Overleaf 失败，无法删除成员: {e}")

    # 5. 更新数据库中的 token (与 revoke_unaccepted_invite 相同)
    crud.update_account_tokens(db, acct, new_csrf, new_sess)

    # 6. 调用 Overleaf API 删除组员 (使用 invite.email_id)
    url = f"https://www.overleaf.com/manage/groups/{acct.group_id}/user/{invite.email_id}"

    logger.info(f"尝试从 Overleaf 删除成员: {url} (email_id: {invite.email_id})")

    resp = session.delete(url, headers={
        "Accept": "application/json",
        "x-csrf-token": new_csrf,
        "Referer": f"https://www.overleaf.com/manage/groups/{acct.group_id}/members",
        "User-Agent": "Mozilla/5.0"
    })

    # 统一错误处理
    if resp.status_code not in (200, 204):
        logger.error(f"删除成员失败: {resp.status_code} {resp.text}")
        try:
            error_data = resp.json()
            error_detail = error_data.get('error', {}).get('message', resp.text)
        except json.JSONDecodeError:
            error_detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=f"删除失败: {error_detail}")

    logger.info(f"成功从 Overleaf 删除成员: {body.email} (email_id: {invite.email_id})")

    # 7. 本地库中将 invites_sent 减 1 (与 revoke_unaccepted_invite 相同)
    if acct.invites_sent > 0:
        acct.invites_sent -= 1
        db.commit()
        db.refresh(acct)

    # —— 标记这条邀请记录已经清理 —— (与 revoke_unaccepted_invite 相同)
    invite.cleaned = True
    db.add(invite)
    db.commit()
    db.refresh(invite)  # 刷新对象以获取最新状态

    return schemas.RemoveMemberResponse(
        status="success",
        detail="成员已删除"
    )


# -------- 新增接口：通过邮箱撤销未接受的邀请 --------
@router.post("/revoke_unaccepted", response_model=schemas.RemoveMemberResponse)
async def revoke_unaccepted_invite(
        body: schemas.MemberEmailRequest,
        db: Session = Depends(get_db)
):
    """
    通过邮箱撤销 Overleaf 组中尚未接受的邀请 (email_id 可能为 None)。
    """
    # 1. 查找最新未清理的邀请记录 (不要求 email_id 存在)
    invite = (
        db.query(models.Invite)
        .filter(
            models.Invite.email == body.email,
            models.Invite.cleaned.is_(False)  # 只处理未清理的邀请记录
        )
        .order_by(models.Invite.created_at.desc())  # 查找最新的记录
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail=f"未找到邮箱 '{body.email}' 的未接受邀请记录")

    # 2. 加载邀请所用账号 (与 remove_member 相同)
    acct = db.get(models.Account, invite.account_id)
    if not acct:
        # 这种情况通常不应该发生，除非账号被删除
        raise HTTPException(status_code=500, detail="找不到邀请账户信息")

    session = requests.Session()
    new_sess = acct.session_cookie
    new_csrf = acct.csrf_token

    # 3. 尝试复用已有的 session/CSRF (与 remove_member 相同)
    if new_sess and new_csrf:
        session.cookies.set(
            "overleaf_session2", new_sess,
            domain=".overleaf.com", path="/"
        )
        try:
            new_sess = await asyncio.to_thread(refresh_session, session, new_csrf)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        except Exception as e:
            logger.warning(f"账号 {acct.email} session/CSRF 刷新失败: {e}. 将尝试完整登录。")
            new_sess = new_csrf = None

    # 4. 如复用失败，完整登录流程 (与 remove_member 相同)
    if not (new_sess and new_csrf):
        try:
            csrf0, sess0 = await get_tokens()
            captcha = get_captcha_token()
            session = await asyncio.to_thread(
                perform_login, csrf0, sess0,
                acct.email, acct.password, captcha
            )
            new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        except Exception as e:
            logger.error(f"账号 {acct.email} 完整登录失败: {e}")
            raise HTTPException(status_code=500, detail=f"登录 Overleaf 失败，无法撤销邀请: {e}")

    # 5. 更新数据库中的 token (与 remove_member 相同)
    crud.update_account_tokens(db, acct, new_csrf, new_sess)

    # 6. 调用 Overleaf API 撤销邀请 (关键改变：使用 email 而非 email_id)
    # 邮箱需要 URL 编码，以防特殊字符 (例如 @)
    encoded_email = requests.utils.quote(body.email, safe='')
    url = f"https://www.overleaf.com/manage/groups/{acct.group_id}/invites/{encoded_email}"

    logger.info(f"尝试撤销 Overleaf 邀请: {url} for email: {body.email}")

    resp = session.delete(url, headers={
        "Accept": "application/json",
        "x-csrf-token": new_csrf,
        "Referer": f"https://www.overleaf.com/manage/groups/{acct.group_id}/members",
        "User-Agent": "Mozilla/5.0"
    })

    # 统一错误处理
    if resp.status_code not in (200, 204):
        logger.error(f"撤销邀请失败: {resp.status_code} {resp.text}")
        try:
            error_data = resp.json()
            error_detail = error_data.get('error', {}).get('message', resp.text)
        except json.JSONDecodeError:
            error_detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=f"撤销邀请失败: {error_detail}")

    logger.info(f"成功撤销 Overleaf 邀请: {body.email}")

    # 7. 更新本地数据库 (标记清理，减少邀请数)
    # 假设未接受的邀请也曾被算作 invites_sent
    if acct.invites_sent > 0:
        acct.invites_sent -= 1
        db.commit()
        db.refresh(acct)

    invite.cleaned = True  # 标记这条邀请记录为已清理
    db.add(invite)
    db.commit()
    db.refresh(invite)  # 刷新对象以获取最新状态

    return schemas.RemoveMemberResponse(
        status="success",
        detail="未接受的邀请已撤销"
    )