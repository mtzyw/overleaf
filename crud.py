# crud.py

import time
from typing import Optional, List
from sqlalchemy.orm import Session
import models

def create_account(
    db: Session,
    email: str,
    password: str,
    group_id: str,
    max_invites: int = 100
) -> models.Account:
    """
    新增一个账号记录
    """
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
    """
    根据 email 删除账号，返回 True 表示删除成功，False 表示未找到
    """
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
        created_at  = now_ts
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec

def create_card(db: Session, code: str, days: int = 7) -> models.Card:
    """
    新增一张卡密，默认有效期 days 天。
    """
    card = models.Card(code=code, days=days)
    db.add(card)
    db.commit()
    db.refresh(card)
    return card

def delete_card(db: Session, code: str) -> bool:
    """
    根据 code 删除卡密。返回 True 表示找到并删除，False 表示未找到。
    """
    card = db.query(models.Card).filter(models.Card.code == code).first()
    if not card:
        return False
    db.delete(card)
    db.commit()
    return True
