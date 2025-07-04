import time
import requests
from typing import Optional
from sqlalchemy.orm import Session
import models
from invite_status_manager import InviteStatusManager

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
    """
    获取卡密，支持新邀请和重新激活两种模式
    """
    return (
        db.query(models.Card)
          .filter(models.Card.code == code, models.Card.used.is_(False))
          .first()
    )

def get_card_for_reactivation(db: Session, code: str, email: str) -> tuple[Optional[models.Card], str]:
    """
    获取卡密用于重新激活，支持权益期内重复使用
    返回: (card|None, status_message)
    """
    card = db.query(models.Card).filter(models.Card.code == code).first()
    
    if not card:
        return None, "卡密不存在"
    
    if not card.used:
        return card, "新卡密可用"
    
    # 检查是否为同用户权益期内重新激活
    import time
    now_ts = int(time.time())
    
    existing_invite = (
        db.query(models.Invite)
        .filter(
            models.Invite.card_id == card.id,
            models.Invite.email == email,
            models.Invite.expires_at > now_ts  # 权益未过期
        )
        .first()
    )
    
    if existing_invite:
        return card, "权益期内可重新激活"
    else:
        return None, "卡密已被其他用户使用或权益已过期"

def get_available_account(db: Session) -> Optional[models.Account]:
    """
    获取可用的账户，使用实时计算的邀请数量
    """
    accounts = (
        db.query(models.Account)
        .order_by(models.Account.updated_at.asc())
        .all()
    )
    
    for account in accounts:
        # 使用实时计算的邀请数量
        real_invites_count = InviteStatusManager.calculate_invites_sent(db, account)
        if real_invites_count < account.max_invites:
            # 如果缓存的计数不准确，同步一下
            if account.invites_sent != real_invites_count:
                account.invites_sent = real_invites_count
                account.updated_at = int(time.time())
                db.commit()
                db.refresh(account)
            return account
    
    return None

def get_available_account_exclude(db: Session, exclude_account_id: int) -> Optional[models.Account]:
    """
    获取可用账户，排除指定账户（通常是失效的原组长）
    """
    accounts = (
        db.query(models.Account)
        .filter(models.Account.id != exclude_account_id)  # 排除原组长
        .order_by(models.Account.updated_at.asc())  # 选择最久未使用的
        .all()
    )
    
    for account in accounts:
        # 使用实时计算的邀请数量
        real_invites_count = InviteStatusManager.calculate_invites_sent(db, account)
        if real_invites_count < account.max_invites:
            # 如果缓存的计数不准确，同步一下
            if account.invites_sent != real_invites_count:
                account.invites_sent = real_invites_count
                account.updated_at = int(time.time())
                db.commit()
                db.refresh(account)
            return account
    
    return None

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
    """
    DEPRECATED: 此函数存在时序问题，请使用 sync_account_invites_count
    增加邀请计数，使用实时同步机制
    """
    # 不再简单+1，而是重新计算
    real_count = InviteStatusManager.calculate_invites_sent(db, account)
    account.invites_sent = real_count
    account.updated_at = int(time.time())
    db.commit()
    db.refresh(account)
    return account

def sync_account_invites_count(db: Session, account: models.Account) -> models.Account:
    """
    同步账户邀请计数到实际值（在记录创建/更新完成后调用）
    """
    real_count = InviteStatusManager.calculate_invites_sent(db, account)
    if account.invites_sent != real_count:
        old_count = account.invites_sent
        account.invites_sent = real_count
        account.updated_at = int(time.time())
        db.commit()
        db.refresh(account)
        print(f"账户 {account.email} 邀请计数同步: {old_count} -> {real_count}")
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
    result: dict,
    new_account: models.Account = None
) -> models.Invite:
    """
    续期时：更新 expires_at、result、success 并重置 cleaned=False；
    如果提供了 new_account，则同时更新 account_id（用于组长变更场景）；
    不修改 created_at，保留首次邀请时间。
    """
    invite.expires_at = new_expires_at
    invite.result     = str(result)
    invite.success    = True
    invite.cleaned    = False
    
    # 如果提供了新的账号，更新 account_id
    if new_account:
        invite.account_id = new_account.id
    
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
    DEPRECATED: 使用 invite_status_manager.batch_cleanup_expired() 替代
    """
    return InviteStatusManager.batch_cleanup_expired(db, limit=100)["total_found"]


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

