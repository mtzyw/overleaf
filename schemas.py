# schemas.py

from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any


# -------- 通用请求模型 --------

class EmailRequest(BaseModel):
    email: EmailStr


# -------- Accounts 相关 --------

class AccountCreate(BaseModel):
    email: EmailStr
    password: str
    group_id: str
    max_invites: Optional[int] = 100

class AccountOut(BaseModel):
    id: int
    email: EmailStr
    group_id: str
    invites_sent: int
    max_invites: int
    updated_at: int

    class Config:
        from_attributes = True


# -------- Cards 相关 --------

class CardCreate(BaseModel):
    code: str
    days: Optional[int] = 7

class CardOut(BaseModel):
    id: int
    code: str
    days: int
    used: bool

    class Config:
        from_attributes = True

class CardDeleteRequest(BaseModel):
    code: str


# -------- Invite 记录 --------

class InviteRequest(BaseModel):
    email: EmailStr
    card: str

class InviteResponse(BaseModel):
    success: bool
    result: Dict[str, Any]
    sent_ts: Optional[int]
    expires_ts: Optional[int]

class InviteRecord(BaseModel):
    id: int
    account_id: int
    card_id: Optional[int]
    email: EmailStr
    email_id: Optional[str]
    expires_at: int
    success: bool
    result: str
    created_at: int

    class Config:
        from_attributes = True


# -------- 更新 email_id --------

class LeaderEmailRequest(BaseModel):
    leader_email: EmailStr

class UpdateEmailIdsResponse(BaseModel):
    leader_email: EmailStr
    total_members: int
    updated_invites: int


# -------- 删除组员 --------

class MemberEmailRequest(BaseModel):
    email: EmailStr

class RemoveMemberResponse(BaseModel):
    status: str
    detail: str

class CleanupResponse(BaseModel):
    cleaned: int   # 本次成功清理的记录数