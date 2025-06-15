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


class GroupMemberInfo(BaseModel):
    member_email: EmailStr
    expires_at: int # Unix 时间戳
    email_id: Optional[str] # Overleaf 上的 user id
# -------- 新增：查询组员信息模型 --------
class LeaderGroupMembersResponse(BaseModel):
    leader_email: EmailStr
    group_id: str
    total_members_in_db: int # 数据库中该组长关联的组员总数 (无论是否过期或清理)
    active_members: List[GroupMemberInfo] # 未过期的组员列表
    expired_members_count: int # 数据库中已过期且未清理的组员数量