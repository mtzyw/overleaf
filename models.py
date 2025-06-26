# models.py

from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey
)
from sqlalchemy.orm import relationship
from database import Base

class Account(Base):
    __tablename__ = "accounts"

    id             = Column(Integer, primary_key=True, index=True)
    email          = Column(String, unique=True, index=True, nullable=False)
    password       = Column(String, nullable=False)
    group_id       = Column(String(64), nullable=False)
    csrf_token     = Column(String, nullable=True)
    session_cookie = Column(String, nullable=True)
    invites_sent   = Column(Integer, default=0)
    max_invites    = Column(Integer, default=100)
    updated_at     = Column(Integer, default=0)  # Unix 时间戳

    invites = relationship("Invite", back_populates="account")


class Card(Base):
    __tablename__ = "cards"

    id    = Column(Integer, primary_key=True, index=True)
    code  = Column(String, unique=True, index=True, nullable=False)
    days  = Column(Integer, default=7)
    used  = Column(Boolean, default=False)

    invites = relationship("Invite", back_populates="card")


class Invite(Base):
    __tablename__ = "invites"

    id          = Column(Integer, primary_key=True, index=True)
    account_id  = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    card_id     = Column(Integer, ForeignKey("cards.id"), nullable=True)
    email       = Column(String, nullable=False)
    email_id    = Column(String, nullable=True)   # 成员在 Overleaf 上的 user id
    expires_at  = Column(Integer, nullable=True) # Unix 时间戳，NULL表示手动添加的用户
    success     = Column(Boolean, nullable=False)
    result      = Column(String, nullable=False)
    created_at  = Column(Integer, nullable=False) # Unix 时间戳
    cleaned     = Column(Boolean, default=False, nullable=False)  # 是否已被清理过期

    account = relationship("Account", back_populates="invites")
    card    = relationship("Card",    back_populates="invites")
