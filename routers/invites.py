import html, json, asyncio, requests
import logging
from datetime import datetime, timedelta
from typing import List, Optional
import time # 新增：引入 time 模块用于获取当前时间戳
from fastapi import APIRouter, Depends, HTTPException, Query, Body # 新增：引入 Body
from sqlalchemy.orm import Session # 新增这一行
import models, crud, schemas
from database import SessionLocal
from overleaf_utils import (
    get_tokens, get_captcha_token,
    perform_login, refresh_session, get_new_csrf
)

router = APIRouter(prefix="/api/v1/invite", tags=["invites"])

# 定义一个日志器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # 可以根据需要调整日志级别
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class GroupFullError(Exception):
    """自定义异常：Overleaf 群组已满"""
    pass

class InviteAttemptFailedError(Exception):
    """自定义异常：单次邀请尝试失败（包括登录、token刷新、发送邀请等任何环节）"""
    pass

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
    """
    发送邀请到 Overleaf。如果失败则抛出 GroupFullError 或 InviteAttemptFailedError。
    """
    url = f"https://www.overleaf.com/manage/groups/{group_id}/invites"
    headers = {
        "x-csrf-token": csrf,
        "Accept": "application/json",
        "Referer": f"https://www.overleaf.com/manage/groups/{group_id}/members",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {"email": email, "expiresAt": expires_iso}

    try:
        resp = session.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status() # 检查 HTTP 状态码，非 2xx 会抛出 requests.HTTPError
        return resp.json()
    except requests.exceptions.HTTPError as http_err:
        try:
            data = resp.json()
            if data.get("error", {}).get("code") == "group_full":
                raise GroupFullError(f"账号组 ({group_id}) 已满: {http_err}")
            else:
                raise InviteAttemptFailedError(f"Overleaf API 返回错误: {resp.status_code} - {data.get('error', {}).get('message', resp.text)}")
        except json.JSONDecodeError:
            raise InviteAttemptFailedError(f"Overleaf API 返回非 JSON 错误: {resp.status_code} - {resp.text}")
    except requests.exceptions.RequestException as req_err:
        raise InviteAttemptFailedError(f"网络请求失败: {req_err}")
    except Exception as e:
        # 捕获其他未知错误
        raise InviteAttemptFailedError(f"发送邀请时发生未知错误: {e}")


async def try_invite_with_account(acct: models.Account, req_email: str, expires_iso: str, db: Session, card: models.Card):
    """
    尝试使用给定账号发送邀请。如果成功返回结果和账号，否则抛出 InviteAttemptFailedError 或 GroupFullError。
    """
    session = requests.Session()
    new_sess = None
    new_csrf = None

    # 1. 尝试复用并刷新 token
    if acct.session_cookie and acct.csrf_token:
        session.cookies.set(
            "overleaf_session2", acct.session_cookie,
            domain=".overleaf.com", path="/"
        )
        try:
            new_sess = await asyncio.to_thread(refresh_session, session, acct.csrf_token)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
            # 如果成功刷新，立即更新数据库，确保下次能用新 token
            crud.update_account_tokens(db, acct, new_csrf, new_sess)
            logger.info(f"账号 {acct.email} token 刷新成功。")
            # 尝试发送邀请
            result = await asyncio.to_thread(send_invite, session, new_csrf, acct.group_id, req_email, expires_iso) # 修改为 req_email
            return result, acct
        except (requests.exceptions.RequestException, RuntimeError, GroupFullError, InviteAttemptFailedError) as e:
            # Token 刷新或使用旧 token 发送邀请失败，记录并尝试完整登录
            logger.warning(f"账号 {acct.email} token 刷新或使用旧 token发送邀请失败: {type(e).__name__} - {e}. 尝试完整登录流程...")
            # 如果是 GroupFullError，我们还是希望它能被外层捕获并特殊处理
            if isinstance(e, GroupFullError):
                raise e
            # 否则，继续尝试完整登录

    # 2. 完整登录流程
    try:
        logger.info(f"账号 {acct.email} 开始完整登录流程...")
        csrf0, sess0 = await get_tokens()
        captcha = get_captcha_token()
        session = await asyncio.to_thread(
            perform_login, csrf0, sess0, acct.email, acct.password, captcha
        )
        new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
        new_csrf = await asyncio.to_thread(get_new_csrf, session, acct.group_id)
        # 完整登录成功后更新数据库 token
        crud.update_account_tokens(db, acct, new_csrf, new_sess)
        logger.info(f"账号 {acct.email} 完整登录成功。")

        # 尝试发送邀请
        result = await asyncio.to_thread(send_invite, session, new_csrf, acct.group_id, req_email, expires_iso)
        return result, acct
    except (requests.exceptions.RequestException, RuntimeError, GroupFullError) as e:
        # 完整登录或发送邀请失败，抛出 InviteAttemptFailedError
        logger.error(f"账号 {acct.email} 完整登录或发送邀请失败: {type(e).__name__} - {e}")
        # 如果是 GroupFullError，仍然保持其类型，方便外层单独捕获处理
        if isinstance(e, GroupFullError):
            raise e
        raise InviteAttemptFailedError(f"账号 {acct.email} 邀请尝试失败: {e}")
    except Exception as e:
        logger.critical(f"账号 {acct.email} 邀请尝试中发生意外错误: {type(e).__name__} - {e}")
        raise InviteAttemptFailedError(f"账号 {acct.email} 邀请尝试中发生意外错误: {e}")


@router.post("", response_model=schemas.InviteResponse)
async def invite(req: schemas.InviteRequest, db: Session = Depends(get_db)):
    # 1. 验证卡密（支持重新激活检测）
    card = crud.get_card(db, req.card)
    is_reactivation = False
    original_invite = None
    
    if not card:
        # 尝试重新激活检测
        card, status_msg = crud.get_card_for_reactivation(db, req.card, req.email)
        if not card:
            logger.warning(f"邀请失败：{status_msg} '{req.card}'")
            raise HTTPException(400, status_msg)
        elif status_msg == "权益期内可重新激活":
            is_reactivation = True
            # 查找原始记录
            original_invite = (
                db.query(models.Invite)
                .filter(
                    models.Invite.card_id == card.id,
                    models.Invite.email == req.email
                )
                .first()
            )
            logger.info(f"检测到重新激活请求：{req.email} 使用卡密 {req.card}")

    # 2. 时间戳处理
    now = datetime.now()
    now_ts = int(now.timestamp())
    
    if is_reactivation and original_invite:
        # 重新激活：使用原有的过期时间
        expires_ts = original_invite.expires_at
        expires_iso = datetime.fromtimestamp(expires_ts).isoformat()
        logger.info(f"重新激活使用原过期时间：{expires_iso}")
    else:
        # 新邀请：计算新的过期时间
        expires = now + timedelta(days=card.days)
        expires_ts = int(expires.timestamp())
        expires_iso = expires.isoformat()

    max_account_attempts = 5 # 最多尝试 5 个不同的账号
    current_attempt = 0
    successful_acct = None
    last_error_detail = "未知错误" # 用于存储最后一次失败的详情

    while current_attempt < max_account_attempts:
        # 3. 获取最不活跃且有可用邀请次数的账号
        # 重新激活时排除原组长，直接使用新组长
        if is_reactivation and original_invite:
            acct = crud.get_available_account_exclude(db, original_invite.account_id)
            logger.info(f"重新激活：排除原组长 ID: {original_invite.account_id}")
        else:
            acct = crud.get_available_account(db)

        if not acct:
            logger.error("所有账号均无可用邀请次数，无法邀请。")
            raise HTTPException(400, "无可用账号")

        logger.info(f"第 {current_attempt + 1} 次尝试使用账号: {acct.email} (ID: {acct.id}) 邀请 {req.email}")

        try:
            result, successful_acct = await try_invite_with_account(acct, req.email, expires_iso, db, card)
            # 如果成功，跳出循环
            break
        except GroupFullError as e:
            # 明确是组满，记录，并尝试下一个账号
            logger.warning(f"账号 {acct.email} 邀请失败，原因：组已满。错误: {e}. 尝试切换账号...")
            last_error_detail = f"账号组 {acct.email} 已满"
            # 标记该账号为“已尝试且失败”
            # 注意：此处更新 updated_at 确保在下次 crud.get_available_account 时，该账号会排到列表后面
            acct.updated_at = int(datetime.now().timestamp())
            db.add(acct)
            db.commit()
            db.refresh(acct)
            current_attempt += 1 # 增加尝试次数
        except InviteAttemptFailedError as e:
            # 其他邀请尝试失败，记录，并尝试下一个账号
            logger.error(f"账号 {acct.email} 邀请失败，原因：{e}. 尝试切换账号...")
            last_error_detail = str(e)
            # 标记该账号为“已尝试且失败”
            acct.updated_at = int(datetime.now().timestamp())
            db.add(acct)
            db.commit()
            db.refresh(acct)
            current_attempt += 1 # 增加尝试次数
        except Exception as e:
            # 捕获任何未预料的异常
            logger.critical(f"账号 {acct.email} 邀请过程中发生未预料的错误: {type(e).__name__} - {e}. 尝试切换账号...")
            last_error_detail = f"未预料的错误: {e}"
            acct.updated_at = int(datetime.now().timestamp())
            db.add(acct)
            db.commit()
            db.refresh(acct)
            current_attempt += 1 # 增加尝试次数


    if not successful_acct:
        # 如果循环结束仍未成功
        logger.error(f"所有可用账号均已尝试，邀请最终失败。最后错误: {last_error_detail}")
        raise HTTPException(400, f"邀请失败：所有可用账号尝试完毕或无可用账号。详情: {last_error_detail}")

    # 4. 更新数据库（只有在成功发送邀请后才执行）
    if is_reactivation and original_invite:
        # 重新激活：不重复标记卡密已使用，只更新记录
        logger.info(f"重新激活模式：更新现有记录，不重复标记卡密已使用")
    else:
        # 新邀请：标记卡密已使用（注意：先标记卡密再创建记录）
        crud.mark_card_used(db, card)

    # 数据库记录处理：重新激活 vs 新邀请
    if is_reactivation and original_invite:
        # 重新激活：直接使用新组长，清理原组长
        old_account = db.get(models.Account, original_invite.account_id)
        cleanup_success = False
        
        # 如果用户在原组长下已被接受，尝试从原组长删除（清理步骤）
        if original_invite.email_id and old_account:
            logger.info(f"重新激活清理：尝试从原组长 {old_account.email} 删除成员 {req.email}")
            
            try:
                # 构造删除函数进行清理
                async def cleanup_original_member():
                    import requests
                    import asyncio
                    from overleaf_utils import refresh_session, get_new_csrf, get_tokens, perform_login, get_captcha_token
                    
                    session = requests.Session()
                    new_sess = old_account.session_cookie
                    new_csrf = old_account.csrf_token
                    
                    # 尝试复用已有的 session/CSRF
                    if new_sess and new_csrf:
                        session.cookies.set("overleaf_session2", new_sess, domain=".overleaf.com", path="/")
                        try:
                            new_sess = await asyncio.to_thread(refresh_session, session, new_csrf)
                            new_csrf = await asyncio.to_thread(get_new_csrf, session, old_account.group_id)
                        except Exception:
                            new_sess = new_csrf = None
                    
                    # 如果复用失败，完整登录
                    if not (new_sess and new_csrf):
                        csrf0, sess0 = await get_tokens()
                        captcha = get_captcha_token()
                        session = await asyncio.to_thread(perform_login, csrf0, sess0, old_account.email, old_account.password, captcha)
                        new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
                        new_csrf = await asyncio.to_thread(get_new_csrf, session, old_account.group_id)
                    
                    # 更新数据库中的 token
                    crud.update_account_tokens(db, old_account, new_csrf, new_sess)
                    
                    # 调用 Overleaf API 删除成员
                    url = f"https://www.overleaf.com/manage/groups/{old_account.group_id}/user/{original_invite.email_id}"
                    resp = session.delete(url, headers={
                        "Accept": "application/json",
                        "x-csrf-token": new_csrf,
                        "Referer": f"https://www.overleaf.com/manage/groups/{old_account.group_id}/members",
                        "User-Agent": "Mozilla/5.0"
                    })
                    
                    if resp.status_code in (200, 204):
                        return {"success": True, "message": "原组长删除成功"}
                    elif resp.status_code == 404:
                        return {"success": True, "message": "成员已不存在"}
                    else:
                        return {"success": False, "message": f"删除失败: {resp.status_code}"}
                
                # 执行清理操作
                cleanup_result = await cleanup_original_member()
                cleanup_success = cleanup_result["success"]
                
                if cleanup_success:
                    logger.info(f"原组长 {old_account.email} 清理成功: {cleanup_result['message']}")
                else:
                    logger.warning(f"原组长 {old_account.email} 清理失败: {cleanup_result['message']}")
                    
            except Exception as e:
                logger.warning(f"原组长 {old_account.email} 清理过程出现异常：{e}")
                cleanup_success = False
        
        # 记录重新激活信息
        result["reactivation_info"] = {
            "type": "reactivation",
            "original_account_id": original_invite.account_id,
            "new_account_id": successful_acct.id,
            "original_account": old_account.email if old_account else "未知",
            "new_account": successful_acct.email,
            "inherited_expires_at": expires_ts,
            "cleanup_attempted": original_invite.email_id is not None,
            "cleanup_success": cleanup_success,
            "strategy": "always_use_new_account"
        }
        
        # 更新记录：更换到新组长，保持其他字段不变
        crud.update_invite_expiry(db, original_invite, expires_ts, result, successful_acct)
        
        logger.info(f"重新激活成功：{req.email} 从组长 {result['reactivation_info']['original_account']} 转移到 {successful_acct.email}")
        
        # 同步账户计数
        if old_account:
            crud.sync_account_invites_count(db, old_account)
        crud.sync_account_invites_count(db, successful_acct)
        
    else:
        # 新邀请：检查跨群组问题并处理
        current_account_record = (
            db.query(models.Invite)
              .filter(
                  models.Invite.email == req.email,
                  models.Invite.account_id == successful_acct.id
              )
              .order_by(models.Invite.created_at.desc())
              .first()
        )
        
        # 检查该邮箱是否存在于其他账户中（跨群组检查）
        other_account_records = (
            db.query(models.Invite)
              .filter(
                  models.Invite.email == req.email,
                  models.Invite.account_id != successful_acct.id,
                  models.Invite.cleaned.is_(False)  # 只检查未清理的记录
              )
              .all()
        )
        
        # 如果存在其他群组的活跃记录，记录警告但继续处理
        if other_account_records:
            other_accounts = []
            for record in other_account_records:
                other_acct = db.get(models.Account, record.account_id)
                other_accounts.append(other_acct.email)
            
            logger.warning(f"⚠️  用户 {req.email} 已存在于其他群组: {', '.join(other_accounts)}")
            logger.warning(f"   当前邀请将在新群组 {successful_acct.email} 中创建记录")
            
            # 在result中记录这个重要信息
            result["cross_group_warning"] = {
                "message": f"用户已存在于其他群组: {', '.join(other_accounts)}",
                "existing_groups": other_accounts,
                "current_group": successful_acct.email,
                "action": "created_new_record_in_current_group"
            }
        
        # 根据当前账户是否有记录决定操作
        if current_account_record:
            # 更新当前账户的记录
            crud.update_invite_expiry(db, current_account_record, expires_ts, result, successful_acct)
            logger.info(f"更新了 {req.email} 在账户 {successful_acct.email} 中的记录")
        else:
            # 在当前账户创建新记录（即使用户在其他群组中存在）
            crud.create_invite_record(db, successful_acct, req.email, expires_ts, True, result, card)
            logger.info(f"为 {req.email} 在账户 {successful_acct.email} 中创建了新记录")
            
        # 5. 新邀请完成后，同步计数（修复计数时序问题）
        crud.sync_account_invites_count(db, successful_acct)
        logger.info(f"已同步账户 {successful_acct.email} 的邀请计数")

    logger.info(f"成功邀请 {req.email} 使用账号 {successful_acct.email}。")

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

# -------- 新增：修改邀请过期时间的接口 --------
@router.post("/update_expiration", response_model=schemas.UpdateExpirationResponse)
async def update_invite_expiration(
    request_data: schemas.InviteUpdateExpirationRequest = Body(...),
    db: Session = Depends(get_db)
):
    """
    根据邮箱更新一个邀请记录的过期时间。
    """
    # 验证新的过期时间是否有效（例如，不能是过去的时间）
    if request_data.expires_at <= int(time.time()): #
        raise HTTPException(
            status_code=400,
            detail="新的过期时间必须是未来的时间。"
        )

    updated_invite = crud.update_invite_expiration_by_email(
        db,
        email=request_data.email,
        new_expires_at=request_data.expires_at
    )

    if not updated_invite:
        raise HTTPException(
            status_code=404,
            detail=f"未找到邮箱 '{request_data.email}' 的邀请记录，无法更新过期时间。"
        )

    return schemas.UpdateExpirationResponse(
        message="Invite expiration time updated successfully.",
        updated_email=updated_invite.email,
        new_expires_at=updated_invite.expires_at,
        invite_id=updated_invite.id
    )


# -------- 新增：卡密检测接口 --------
@router.get("/detect", response_model=schemas.CardDetectResponse)
def detect_card_status(
    card: str = Query(..., description="卡密代码"),
    db: Session = Depends(get_db)
):
    """
    检测卡密状态，判断是新邀请还是重新激活模式
    """
    import time
    
    # 查找卡密
    card_obj = db.query(models.Card).filter(models.Card.code == card).first()
    
    if not card_obj:
        return schemas.CardDetectResponse(
            mode="normal",
            can_reactivate=False,
            message="卡密不存在"
        )
    
    if not card_obj.used:
        return schemas.CardDetectResponse(
            mode="normal",
            can_reactivate=False,
            message="新卡密，请输入邮箱进行首次邀请"
        )
    
    # 查找该卡密关联的邀请记录
    invite_record = (
        db.query(models.Invite)
        .filter(models.Invite.card_id == card_obj.id)
        .first()
    )
    
    if not invite_record:
        return schemas.CardDetectResponse(
            mode="normal",
            can_reactivate=False,
            message="卡密已使用但找不到关联记录"
        )
    
    # 检查权益是否有效
    now_ts = int(time.time())
    if invite_record.expires_at <= now_ts:
        return schemas.CardDetectResponse(
            mode="normal",
            can_reactivate=False,
            message="权益已过期，请购买新卡密"
        )
    
    # 计算剩余天数
    remaining_seconds = invite_record.expires_at - now_ts
    remaining_days = max(1, int(remaining_seconds / 86400))
    
    return schemas.CardDetectResponse(
        mode="reactivate",
        email=invite_record.email,
        remaining_days=remaining_days,
        expires_at=invite_record.expires_at,
        can_reactivate=True,
        message=f"检测到绑定邮箱：{invite_record.email}，剩余{remaining_days}天权益"
    )


# -------- 新增：一键重新激活接口 --------
@router.post("/reactivate", response_model=schemas.InviteResponse)
async def reactivate_by_card_only(
    req: schemas.ReactivateRequest,
    db: Session = Depends(get_db)
):
    """
    通过卡密一键重新激活，自动识别绑定的邮箱
    """
    import time
    
    # 1. 验证卡密和查找关联邮箱
    card = db.query(models.Card).filter(models.Card.code == req.card).first()
    if not card:
        logger.warning(f"重新激活失败：卡密不存在 '{req.card}'")
        raise HTTPException(400, "卡密不存在")
    
    if not card.used:
        logger.warning(f"重新激活失败：卡密尚未使用过 '{req.card}'")
        raise HTTPException(400, "该卡密尚未使用过，请使用正常邀请流程")
    
    # 2. 查找该卡密关联的邮箱
    invite_record = (
        db.query(models.Invite)
        .filter(models.Invite.card_id == card.id)
        .first()
    )
    
    if not invite_record:
        logger.warning(f"重新激活失败：找不到卡密关联的邀请记录 '{req.card}'")
        raise HTTPException(400, "找不到该卡密的使用记录")
    
    # 3. 验证权益是否还有效
    now_ts = int(time.time())
    if invite_record.expires_at <= now_ts:
        logger.warning(f"重新激活失败：权益已过期 '{req.card}' for {invite_record.email}")
        raise HTTPException(400, "权益已过期，请购买新卡密")
    
    logger.info(f"检测到一键重新激活请求：卡密 {req.card} → 邮箱 {invite_record.email}")
    
    # 4. 构造邀请请求并调用原有逻辑
    fake_request = schemas.InviteRequest(
        email=invite_record.email,
        card=req.card
    )
    
    # 调用原有的邀请逻辑（会自动检测为重新激活）
    return await invite(fake_request, db)