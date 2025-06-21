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
    # 1. 验证卡密
    card = crud.get_card(db, req.card)
    if not card:
        logger.warning(f"邀请失败：无效或已使用的卡密 '{req.card}'")
        raise HTTPException(400, "无效或已使用的卡密")

    # 2. 时间戳处理
    now = datetime.now()
    expires = now + timedelta(days=card.days)
    now_ts = int(now.timestamp())
    expires_ts = int(expires.timestamp())
    expires_iso = expires.isoformat()

    max_account_attempts = 5 # 最多尝试 5 个不同的账号
    current_attempt = 0
    successful_acct = None
    last_error_detail = "未知错误" # 用于存储最后一次失败的详情

    while current_attempt < max_account_attempts:
        # 3. 获取最不活跃且有可用邀请次数的账号
        # 重要的改动：每次失败后，我们更新了失败账号的 updated_at，
        # 这样下次 get_available_account 就能选到不同的账号
        acct = crud.get_available_account(db) # crud.py 中的这个函数返回的是按 updated_at 升序排列的第一个

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
    # 在这里才真正增加 invites_sent 计数和标记卡密已使用
    crud.increment_invites(db, successful_acct)
    crud.mark_card_used(db, card)

    # 检查是否存在针对该邮箱的旧邀请记录，如果有则更新，否则创建新记录
    last_invite_record = (
        db.query(models.Invite)
          .filter(models.Invite.email == req.email)
          .order_by(models.Invite.created_at.desc())
          .first()
    )
    if last_invite_record:
        # 传入新的账号信息，确保 account_id 也会更新
        crud.update_invite_expiry(db, last_invite_record, expires_ts, result, successful_acct)
    else:
        crud.create_invite_record(db, successful_acct, req.email, expires_ts, True, result, card)

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