import logging
import requests
import asyncio
import json  # 新增：用于处理 JSON 响应
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models, schemas, crud
from database import SessionLocal
from invite_status_manager import InviteStatusManager, TransactionManager
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
    使用新的状态管理和事务处理逻辑。
    """
    # 1. 查找最新的可删除邀请记录
    invite = (
        db.query(models.Invite)
        .filter(models.Invite.email == body.email)
        .order_by(models.Invite.created_at.desc())
        .first()
    )
    
    if not invite:
        raise HTTPException(status_code=404, detail="未找到邀请记录")
    
    # 2. 使用状态管理器检查是否可删除
    if not InviteStatusManager.is_removable(invite):
        status = InviteStatusManager.get_invite_status(invite)
        raise HTTPException(
            status_code=400, 
            detail=f"邀请不可删除，当前状态: {status.value}"
        )

    # 3. 获取账户信息
    acct = db.get(models.Account, invite.account_id)
    if not acct:
        raise HTTPException(status_code=500, detail="找不到邀请账户信息")

    # 4. 定义删除操作函数
    async def perform_overleaf_deletion():
        session = requests.Session()
        new_sess = acct.session_cookie
        new_csrf = acct.csrf_token

        # 尝试复用已有的 session/CSRF
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

        # 如复用失败，完整登录流程
        if not (new_sess and new_csrf):
            csrf0, sess0 = await get_tokens()
            captcha = get_captcha_token()
            session = await asyncio.to_thread(
                perform_login, csrf0, sess0,
                acct.email, acct.password, captcha
            )
            new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)

        # 更新数据库中的 token
        crud.update_account_tokens(db, acct, new_csrf, new_sess)

        # 调用 Overleaf API 删除组员
        url = f"https://www.overleaf.com/manage/groups/{acct.group_id}/user/{invite.email_id}"
        
        logger.info(f"尝试从 Overleaf 删除成员: {url} (email_id: {invite.email_id})")

        resp = session.delete(url, headers={
            "Accept": "application/json",
            "x-csrf-token": new_csrf,
            "Referer": f"https://www.overleaf.com/manage/groups/{acct.group_id}/members",
            "User-Agent": "Mozilla/5.0"
        })

        # 处理不同的响应状态
        if resp.status_code in (200, 204):
            logger.info(f"成功从 Overleaf 删除成员: {body.email}")
            return {"success": True, "message": "删除成功"}
        elif resp.status_code == 404:
            logger.warning(f"成员已不存在: {body.email}，标记为已处理")
            return {"success": True, "message": "成员已不存在"}
        else:
            # 其他错误抛出异常，让事务管理器处理
            try:
                error_data = resp.json()
                error_detail = error_data.get('error', {}).get('message', resp.text)
            except json.JSONDecodeError:
                error_detail = resp.text
            raise Exception(f"Overleaf API错误 {resp.status_code}: {error_detail}")

    # 5. 使用事务管理器执行删除操作（真正删除记录）
    result = await TransactionManager.safe_remove_member(db, invite, perform_overleaf_deletion, delete_record=True)
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])

    return schemas.RemoveMemberResponse(
        status="success",
        detail=result["message"]
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

    # 7. 更新本地数据库 (真正删除记录)
    db.delete(invite)
    db.commit()
    
    # 8. 重新计算账户的邀请计数
    InviteStatusManager.sync_account_invites_count(db, acct)

    return schemas.RemoveMemberResponse(
        status="success",
        detail="未接受的邀请已撤销"
    )


# -------- 新增接口：批量清理过期成员 --------
@router.post("/cleanup_expired", response_model=schemas.CleanupResponse)
async def cleanup_expired_members(
        db: Session = Depends(get_db)
):
    """
    批量清理所有过期的邀请记录，使用新的状态管理逻辑。
    """
    import time
    
    now_ts = int(time.time())
    
    # 查找所有过期且未清理的邀请记录
    expired_invites = (
        db.query(models.Invite)
        .filter(
            models.Invite.expires_at < now_ts,
            models.Invite.cleaned.is_(False)
        )
        .limit(100)  # 限制批量处理数量
        .all()
    )
    
    if not expired_invites:
        return schemas.CleanupResponse(
            status="success",
            detail="没有需要清理的过期邀请",
            processed_count=0,
            success_count=0,
            error_count=0
        )
    
    success_count = 0
    error_count = 0
    
    for invite in expired_invites:
        try:
            status = InviteStatusManager.get_invite_status(invite)
            
            if status == InviteStatusManager.InviteStatus.ACCEPTED:
                # 已接受的邀请，需要调用删除成员接口
                body = schemas.MemberEmailRequest(email=invite.email)
                result = await remove_member(body, db)
                success_count += 1
                logger.info(f"清理过期成员成功: {invite.email} (ID: {invite.id})")
                
            elif status == InviteStatusManager.InviteStatus.PENDING:
                # 未接受的邀请，直接标记为已处理
                InviteStatusManager.mark_invite_processed(db, invite, "expired_pending")
                success_count += 1
                logger.info(f"清理过期邀请成功: {invite.email} (ID: {invite.id})")
                
            else:
                # 其他状态，直接标记为已处理
                InviteStatusManager.mark_invite_processed(db, invite, "expired_other")
                success_count += 1
                logger.info(f"标记过期邀请为已处理: {invite.email} (ID: {invite.id})")
                
        except HTTPException as e:
            if e.status_code == 404:
                # 404错误：直接标记为已处理
                InviteStatusManager.mark_invite_processed(db, invite, "not_found")
                success_count += 1
                logger.warning(f"过期邀请成员不存在，已标记为已处理: {invite.email} (ID: {invite.id})")
            else:
                error_count += 1
                logger.error(f"清理过期邀请失败: {invite.email} (ID: {invite.id}) - {e.detail}")
        except Exception as e:
            error_count += 1
            logger.error(f"清理过期邀请异常: {invite.email} (ID: {invite.id}) - {str(e)}")
    
    # 同步所有相关账户的计数
    affected_accounts = set(invite.account_id for invite in expired_invites)
    for account_id in affected_accounts:
        account = db.get(models.Account, account_id)
        if account:
            InviteStatusManager.sync_account_invites_count(db, account)
    
    return schemas.CleanupResponse(
        status="success",
        detail=f"清理完成：成功 {success_count} 个，失败 {error_count} 个",
        processed_count=len(expired_invites),
        success_count=success_count,
        error_count=error_count
    )


# -------- 数据验证和状态监控接口 --------
@router.get("/status/validation")
async def validate_system_status(db: Session = Depends(get_db)):
    """验证系统数据一致性"""
    import time
    issues = InviteStatusManager.validate_data_consistency(db)
    return {
        "total_issues": len(issues),
        "issues": issues,
        "checked_at": int(time.time())
    }


@router.get("/status/account/{account_email}")
async def get_account_status(account_email: str, db: Session = Depends(get_db)):
    """获取指定账户的详细状态"""
    account = db.query(models.Account).filter(models.Account.email == account_email).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")
    return InviteStatusManager.get_account_status_summary(db, account)


@router.post("/fix/account_counts")
async def fix_account_counts_api(db: Session = Depends(get_db)):
    """修复所有账户的邀请计数"""
    import time
    accounts = db.query(models.Account).all()
    fixed_count = 0
    
    for account in accounts:
        old_count = account.invites_sent
        InviteStatusManager.sync_account_invites_count(db, account)
        if account.invites_sent != old_count:
            fixed_count += 1
    
    return {
        "fixed_accounts": fixed_count,
        "total_accounts": len(accounts),
        "fixed_at": int(time.time())
    }


@router.get("/status/global")
async def get_global_status(db: Session = Depends(get_db)):
    """获取全局系统状态"""
    accounts = db.query(models.Account).all()
    
    total_invites = 0
    total_quota = 0
    status_stats = {"pending": 0, "accepted": 0, "expired": 0, "processed": 0}
    
    for account in accounts:
        summary = InviteStatusManager.get_account_status_summary(db, account)
        total_invites += summary['invites_sent_real']
        total_quota += summary['max_invites']
        
        for status, count in summary['status_breakdown'].items():
            if status in status_stats:
                status_stats[status] += count
    
    return {
        "accounts_count": len(accounts),
        "total_active_invites": total_invites,
        "total_quota": total_quota,
        "quota_utilization": round(total_invites/total_quota*100, 1) if total_quota > 0 else 0,
        "status_distribution": status_stats
    }