import time
import requests
from typing import Optional
from sqlalchemy.orm import Session
import models

def create_account(
    db: Session,
    email: str,
    password: str,
    group_id: str,
    max_invites: int = 100
) -> models.Account:
    acct = models.Account(
        email=email,
        password=password,
        group_id=group_id,
        max_invites=max_invites,
        invites_sent=0,
        updated_at=int(time.time())
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct

def delete_account(db: Session, email: str) -> bool:
    acct = db.query(models.Account).filter(models.Account.email == email).first()
    if not acct:
        return False
    db.delete(acct)
    db.commit()
    return True

def get_card(db: Session, code: str) -> Optional[models.Card]:
    return (
        db.query(models.Card)
          .filter(models.Card.code == code, models.Card.used.is_(False))
          .first()
    )

def get_available_account(db: Session) -> Optional[models.Account]:
    return (
        db.query(models.Account)
          .filter(models.Account.invites_sent < models.Account.max_invites)
          .order_by(models.Account.updated_at.asc())
          .first()
    )

def update_account_tokens(
    db: Session,
    account: models.Account,
    csrf_token: str,
    session_cookie: str
) -> models.Account:
    account.csrf_token     = csrf_token
    account.session_cookie = session_cookie
    account.updated_at     = int(time.time())
    db.commit()
    db.refresh(account)
    return account

def increment_invites(db: Session, account: models.Account) -> models.Account:
    account.invites_sent += 1
    account.updated_at   = int(time.time())
    db.commit()
    db.refresh(account)
    return account

def mark_card_used(db: Session, card: models.Card) -> models.Card:
    card.used = True
    db.commit()
    db.refresh(card)
    return card

def create_invite_record(
    db: Session,
    account: models.Account,
    email: str,
    expires_ts: int,
    success: bool,
    result: dict,
    card: Optional[models.Card] = None
) -> models.Invite:
    now_ts = int(time.time())
    rec = models.Invite(
        account_id  = account.id,
        card_id     = card.id if card else None,
        email       = email,
        email_id    = None,
        expires_at  = expires_ts,
        success     = success,
        result      = str(result),
        created_at  = now_ts,
        cleaned     = False
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec

def update_invite_expiry(
    db: Session,
    invite: models.Invite,
    new_expires_at: int,
    result: dict
) -> models.Invite:
    """
    续期时：更新 expires_at、result、success 并重置 cleaned=False；
    不修改 created_at，保留首次邀请时间。
    """
    invite.expires_at = new_expires_at
    invite.result     = str(result)
    invite.success    = True
    invite.cleaned    = False
    db.commit()
    db.refresh(invite)
    return invite

def create_card(db: Session, code: str, days: int = 7) -> models.Card:
    card = models.Card(code=code, days=days)
    db.add(card)
    db.commit()
    db.refresh(card)
    return card

def delete_card(db: Session, code: str) -> bool:
    card = db.query(models.Card).filter(models.Card.code == code).first()
    if not card:
        return False
    db.delete(card)
    db.commit()
    return True

def clean_expired_invites(db: Session) -> int:
    """
    查找所有 expires_at < now 且 cleaned=False 的 Invite，
    调用删除接口后标记 cleaned=True。
    返回成功清理的条数。
    """
    now_ts = int(time.time())
    expired = (
        db.query(models.Invite)
          .filter(models.Invite.expires_at < now_ts,
                  models.Invite.cleaned.is_(False))
          .all()
    )
    count = 0
    for inv in expired:
        try:
            resp = requests.post(
                "https://overapi.shayudata.com/api/v1/member/remove",
                json={"email": inv.email},
                timeout=10
            )
            if resp.status_code in (200, 204):
                inv.cleaned = True
                db.commit()
                count += 1
        except Exception:
            # 出错下次再试
            continue
    return count


def update_invite_expiration_by_email(
    db: Session,
    email: str,
    new_expires_at: int
) -> Optional[models.Invite]:
    """
    根据邮箱更新最新邀请记录的过期时间。
    如果找到记录并更新成功，返回更新后的 Invite 记录对象；否则返回 None。
    """
    # 查找指定邮箱的最新一条邀请记录
    invite = (
        db.query(models.Invite)
        .filter(models.Invite.email == email)
        .order_by(models.Invite.created_at.desc()) # 查找最新记录
        .first()
    )

    if not invite:
        return None # 未找到对应的邀请记录

    invite.expires_at = new_expires_at
    invite.cleaned = False # 假设续期后，该邀请不再是已清理状态

    # 根据您的业务逻辑，您可能还需要更新其他字段，例如 `result`。
    # 如果需要更新 result 字段，可以这样处理（示例）：
    # from datetime import datetime
    # updated_time_str = datetime.fromtimestamp(new_expires_at).isoformat()
    # invite.result = f"{{'status': 'expiration_updated', 'new_expires_at_iso': '{updated_time_str}'}}"

    db.add(invite) # 标记对象为已修改
    db.commit()    # 提交更改到数据库
    db.refresh(invite) # 刷新对象以获取最新状态

    return invite

