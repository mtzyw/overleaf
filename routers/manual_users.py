#!/usr/bin/env python3
"""
手动用户管理API路由 - 管理expires_at=NULL的手动添加用户
"""

import json
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, validator
from sqlalchemy.orm import Session
from sqlalchemy import and_

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models

# 创建路由器
router = APIRouter(prefix="/api/v1/manual-users", tags=["手动用户管理"])

# 依赖项：获取数据库会话
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 请求/响应模型
class ManualUser(BaseModel):
    """手动用户信息"""
    id: int
    email: str
    account_email: str
    account_id: int
    group_id: str
    email_id: Optional[str]
    card_id: Optional[int]
    created_at: str
    sync_date: Optional[str]
    overleaf_status: Optional[str]
    note: Optional[str]
    action_required: Optional[str]

class SetExpiryRequest(BaseModel):
    """设置过期时间请求"""
    days: int
    card_id: Optional[int] = None
    note: Optional[str] = None
    
    @validator('days')
    def validate_days(cls, v):
        if v <= 0 or v > 365:
            raise ValueError('过期天数必须在1-365之间')
        return v

class ManualUserStats(BaseModel):
    """手动用户统计"""
    total_manual_users: int
    by_account: Dict[str, int]
    accepted_count: int
    pending_count: int
    without_card_count: int

class BulkSetExpiryRequest(BaseModel):
    """批量设置过期时间请求"""
    user_ids: List[int]
    days: int
    card_id: Optional[int] = None
    note: Optional[str] = None

@router.get("/list", response_model=List[ManualUser])
async def list_manual_users(
    account_email: Optional[str] = Query(None, description="按账户筛选"),
    limit: int = Query(100, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    """获取所有手动添加的用户列表"""
    query = (
        db.query(models.Invite)
        .join(models.Account)
        .filter(models.Invite.expires_at.is_(None))
        .filter(models.Invite.cleaned == False)
    )
    
    if account_email:
        query = query.filter(models.Account.email == account_email)
    
    invites = query.limit(limit).all()
    
    manual_users = []
    for invite in invites:
        # 解析result中的额外信息
        result_data = {}
        if invite.result:
            try:
                result_data = json.loads(invite.result)
            except:
                pass
        
        manual_users.append(ManualUser(
            id=invite.id,
            email=invite.email,
            account_email=invite.account.email,
            account_id=invite.account_id,
            group_id=invite.account.group_id,
            email_id=invite.email_id,
            card_id=invite.card_id,
            created_at=datetime.fromtimestamp(invite.created_at).strftime('%Y-%m-%d %H:%M:%S'),
            sync_date=result_data.get('sync_date'),
            overleaf_status=result_data.get('overleaf_status'),
            note=result_data.get('note'),
            action_required=result_data.get('action_required')
        ))
    
    return manual_users

@router.get("/stats", response_model=ManualUserStats)
async def get_manual_user_stats(db: Session = Depends(get_db)):
    """获取手动用户统计信息"""
    manual_invites = (
        db.query(models.Invite)
        .join(models.Account)
        .filter(models.Invite.expires_at.is_(None))
        .filter(models.Invite.cleaned == False)
        .all()
    )
    
    # 按账户统计
    by_account = {}
    accepted_count = 0
    pending_count = 0
    without_card_count = 0
    
    for invite in manual_invites:
        account_email = invite.account.email
        by_account[account_email] = by_account.get(account_email, 0) + 1
        
        if invite.email_id:
            accepted_count += 1
        else:
            pending_count += 1
            
        if not invite.card_id:
            without_card_count += 1
    
    return ManualUserStats(
        total_manual_users=len(manual_invites),
        by_account=by_account,
        accepted_count=accepted_count,
        pending_count=pending_count,
        without_card_count=without_card_count
    )

@router.post("/{user_id}/set-expiry")
async def set_user_expiry(
    user_id: int,
    request: SetExpiryRequest,
    db: Session = Depends(get_db)
):
    """为手动用户设置过期时间"""
    # 查找用户
    invite = (
        db.query(models.Invite)
        .filter(
            and_(
                models.Invite.id == user_id,
                models.Invite.expires_at.is_(None),
                models.Invite.cleaned == False
            )
        )
        .first()
    )
    
    if not invite:
        raise HTTPException(status_code=404, detail="手动用户不存在或已设置过期时间")
    
    # 计算过期时间戳
    expiry_date = datetime.now() + timedelta(days=request.days)
    expires_at = int(expiry_date.timestamp())
    
    # 更新记录
    invite.expires_at = expires_at
    if request.card_id:
        invite.card_id = request.card_id
    
    # 更新result信息
    result_data = {}
    if invite.result:
        try:
            result_data = json.loads(invite.result)
        except:
            pass
    
    result_data.update({
        "expiry_set_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "expires_at": expiry_date.strftime('%Y-%m-%d %H:%M:%S'),
        "expiry_days": request.days,
        "card_id_assigned": request.card_id,
        "status": "active_with_expiry",
        "note": request.note or result_data.get('note', ''),
        "warning": "现在有过期时间，到期会被正常清理删除"
    })
    
    invite.result = json.dumps(result_data, ensure_ascii=False)
    
    # 重新计算账户邀请计数
    manager = InviteStatusManager()
    invite.account.invites_sent = manager.calculate_invites_sent(db, invite.account)
    
    db.commit()
    
    return {
        "message": f"已为用户 {invite.email} 设置 {request.days} 天过期时间",
        "user_email": invite.email,
        "expires_at": expiry_date.strftime('%Y-%m-%d %H:%M:%S'),
        "card_id": request.card_id,
        "account_email": invite.account.email
    }

@router.post("/bulk-set-expiry")
async def bulk_set_expiry(
    request: BulkSetExpiryRequest,
    db: Session = Depends(get_db)
):
    """批量设置过期时间"""
    # 查找所有指定的手动用户
    invites = (
        db.query(models.Invite)
        .filter(
            and_(
                models.Invite.id.in_(request.user_ids),
                models.Invite.expires_at.is_(None),
                models.Invite.cleaned == False
            )
        )
        .all()
    )
    
    if not invites:
        raise HTTPException(status_code=404, detail="未找到符合条件的手动用户")
    
    # 计算过期时间戳
    expiry_date = datetime.now() + timedelta(days=request.days)
    expires_at = int(expiry_date.timestamp())
    
    updated_users = []
    affected_accounts = set()
    
    for invite in invites:
        # 更新记录
        invite.expires_at = expires_at
        if request.card_id:
            invite.card_id = request.card_id
        
        # 更新result信息
        result_data = {}
        if invite.result:
            try:
                result_data = json.loads(invite.result)
            except:
                pass
        
        result_data.update({
            "expiry_set_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "expires_at": expiry_date.strftime('%Y-%m-%d %H:%M:%S'),
            "expiry_days": request.days,
            "card_id_assigned": request.card_id,
            "status": "active_with_expiry",
            "note": request.note or result_data.get('note', ''),
            "warning": "现在有过期时间，到期会被正常清理删除",
            "bulk_operation": True
        })
        
        invite.result = json.dumps(result_data, ensure_ascii=False)
        
        updated_users.append({
            "email": invite.email,
            "account_email": invite.account.email
        })
        affected_accounts.add(invite.account_id)
    
    # 重新计算受影响账户的邀请计数
    manager = InviteStatusManager()
    for account_id in affected_accounts:
        account = db.get(models.Account, account_id)
        if account:
            account.invites_sent = manager.calculate_invites_sent(db, account)
    
    db.commit()
    
    return {
        "message": f"已为 {len(updated_users)} 个用户设置 {request.days} 天过期时间",
        "updated_count": len(updated_users),
        "expires_at": expiry_date.strftime('%Y-%m-%d %H:%M:%S'),
        "affected_accounts": len(affected_accounts),
        "updated_users": updated_users
    }

@router.delete("/{user_id}")
async def delete_manual_user(
    user_id: int,
    reason: str = Query(..., description="删除原因"),
    db: Session = Depends(get_db)
):
    """删除手动用户（标记为已清理）"""
    invite = (
        db.query(models.Invite)
        .filter(
            and_(
                models.Invite.id == user_id,
                models.Invite.expires_at.is_(None),
                models.Invite.cleaned == False
            )
        )
        .first()
    )
    
    if not invite:
        raise HTTPException(status_code=404, detail="手动用户不存在或已被处理")
    
    # 标记为已清理
    invite.cleaned = True
    
    # 更新result信息
    result_data = {}
    if invite.result:
        try:
            result_data = json.loads(invite.result)
        except:
            pass
    
    result_data.update({
        "deleted_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "delete_reason": reason,
        "status": "manually_deleted",
        "note": f"手动删除: {reason}"
    })
    
    invite.result = json.dumps(result_data, ensure_ascii=False)
    
    # 重新计算账户邀请计数
    manager = InviteStatusManager()
    invite.account.invites_sent = manager.calculate_invites_sent(db, invite.account)
    
    db.commit()
    
    return {
        "message": f"已删除手动用户 {invite.email}",
        "user_email": invite.email,
        "account_email": invite.account.email,
        "reason": reason
    }

@router.get("/{user_id}/details")
async def get_manual_user_details(
    user_id: int,
    db: Session = Depends(get_db)
):
    """获取手动用户详细信息"""
    invite = (
        db.query(models.Invite)
        .join(models.Account)
        .filter(models.Invite.id == user_id)
        .first()
    )
    
    if not invite:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 解析result数据
    result_data = {}
    if invite.result:
        try:
            result_data = json.loads(invite.result)
        except:
            pass
    
    return {
        "id": invite.id,
        "email": invite.email,
        "account_email": invite.account.email,
        "group_id": invite.account.group_id,
        "email_id": invite.email_id,
        "card_id": invite.card_id,
        "expires_at": invite.expires_at,
        "is_manual": invite.expires_at is None,
        "cleaned": invite.cleaned,
        "created_at": datetime.fromtimestamp(invite.created_at).strftime('%Y-%m-%d %H:%M:%S'),
        "success": invite.success,
        "result_data": result_data,
        "status": InviteStatusManager.get_invite_status(invite).value
    }