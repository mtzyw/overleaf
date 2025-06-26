#!/usr/bin/env python3
"""
数据一致性检查和修复API路由
"""

from typing import Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import SessionLocal
from invite_status_manager import InviteStatusManager, InviteStatus
import models

# 创建路由器
router = APIRouter(prefix="/api/v1/data-consistency", tags=["数据一致性"])

# 依赖项：获取数据库会话
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 响应模型
class AccountConsistency(BaseModel):
    """账户一致性信息"""
    email: str
    account_id: int
    group_id: str
    cached_count: int
    actual_count: int
    difference: int
    is_consistent: bool
    quota_used: int
    quota_total: int
    quota_available: int
    status_distribution: Dict[str, int]

class SystemConsistency(BaseModel):
    """系统一致性报告"""
    total_accounts: int
    consistent_accounts: int
    inconsistent_accounts: int
    accounts: List[AccountConsistency]
    global_stats: Dict[str, int]
    total_active_invites: int
    total_quota: int
    quota_utilization: float

class ValidationResult(BaseModel):
    """验证结果"""
    is_valid: bool
    issues_found: List[str]
    accounts_with_issues: List[str]
    suggested_actions: List[str]

class FixResult(BaseModel):
    """修复结果"""
    accounts_fixed: int
    total_accounts: int
    fixes_applied: List[Dict[str, str]]

@router.get("/validate", response_model=ValidationResult)
async def validate_data_consistency(db: Session = Depends(get_db)):
    """验证系统数据一致性"""
    accounts = db.query(models.Account).all()
    issues_found = []
    accounts_with_issues = []
    
    manager = InviteStatusManager()
    
    for account in accounts:
        # 计算实际邀请数
        actual_count = manager.calculate_invites_sent(db, account)
        cached_count = account.invites_sent
        
        if actual_count != cached_count:
            issue = f"账户 {account.email}: 缓存计数({cached_count}) != 实际计数({actual_count})"
            issues_found.append(issue)
            accounts_with_issues.append(account.email)
        
        # 检查是否有孤立的邀请记录
        invites = db.query(models.Invite).filter(models.Invite.account_id == account.id).all()
        for invite in invites:
            status = manager.get_invite_status(invite)
            
            # 检查状态逻辑一致性
            if invite.cleaned and status in [InviteStatus.PENDING, InviteStatus.ACCEPTED]:
                issue = f"邀请记录 {invite.id} ({invite.email}): 标记为已清理但状态为 {status.value}"
                issues_found.append(issue)
                if account.email not in accounts_with_issues:
                    accounts_with_issues.append(account.email)
            
            if invite.email_id and status == InviteStatus.PENDING:
                issue = f"邀请记录 {invite.id} ({invite.email}): 有email_id但状态为PENDING"
                issues_found.append(issue)
                if account.email not in accounts_with_issues:
                    accounts_with_issues.append(account.email)
    
    # 检查卡密关联
    orphaned_invites = (
        db.query(models.Invite)
        .filter(models.Invite.card_id.isnot(None))
        .filter(models.Invite.expires_at.isnot(None))  # 排除手动用户
        .outerjoin(models.Card, models.Invite.card_id == models.Card.id)
        .filter(models.Card.id.is_(None))
        .count()
    )
    
    if orphaned_invites > 0:
        issues_found.append(f"发现 {orphaned_invites} 个邀请记录关联了不存在的卡密")
    
    # 生成建议操作
    suggested_actions = []
    if len(accounts_with_issues) > 0:
        suggested_actions.append("使用 /fix-counts 修复账户计数不一致问题")
    if orphaned_invites > 0:
        suggested_actions.append("检查并修复孤立的卡密关联")
    if not issues_found:
        suggested_actions.append("系统数据一致性良好，无需修复")
    
    return ValidationResult(
        is_valid=len(issues_found) == 0,
        issues_found=issues_found,
        accounts_with_issues=accounts_with_issues,
        suggested_actions=suggested_actions
    )

@router.get("/report", response_model=SystemConsistency)
async def get_consistency_report(db: Session = Depends(get_db)):
    """生成完整的数据一致性报告"""
    accounts = db.query(models.Account).all()
    manager = InviteStatusManager()
    
    account_reports = []
    total_active_invites = 0
    total_quota = 0
    global_status_counts = {"pending": 0, "accepted": 0, "expired": 0, "processed": 0}
    consistent_count = 0
    
    for account in accounts:
        # 计算实际邀请数
        actual_count = manager.calculate_invites_sent(db, account)
        cached_count = account.invites_sent
        is_consistent = actual_count == cached_count
        
        if is_consistent:
            consistent_count += 1
        
        # 获取状态分布
        invites = db.query(models.Invite).filter(models.Invite.account_id == account.id).all()
        status_distribution = {"pending": 0, "accepted": 0, "expired": 0, "processed": 0}
        
        for invite in invites:
            status = manager.get_invite_status(invite).value
            status_distribution[status] += 1
            global_status_counts[status] += 1
        
        quota_total = 22  # 假设每个账户配额为22
        quota_used = actual_count
        quota_available = max(0, quota_total - quota_used)
        
        total_active_invites += actual_count
        total_quota += quota_total
        
        account_reports.append(AccountConsistency(
            email=account.email,
            account_id=account.id,
            group_id=account.group_id,
            cached_count=cached_count,
            actual_count=actual_count,
            difference=cached_count - actual_count,
            is_consistent=is_consistent,
            quota_used=quota_used,
            quota_total=quota_total,
            quota_available=quota_available,
            status_distribution=status_distribution
        ))
    
    quota_utilization = (total_active_invites / total_quota * 100) if total_quota > 0 else 0
    
    return SystemConsistency(
        total_accounts=len(accounts),
        consistent_accounts=consistent_count,
        inconsistent_accounts=len(accounts) - consistent_count,
        accounts=account_reports,
        global_stats=global_status_counts,
        total_active_invites=total_active_invites,
        total_quota=total_quota,
        quota_utilization=round(quota_utilization, 1)
    )

@router.post("/fix-counts", response_model=FixResult)
async def fix_account_counts(
    dry_run: bool = Query(False, description="是否只是预览，不实际修复"),
    db: Session = Depends(get_db)
):
    """修复所有账户的邀请计数"""
    accounts = db.query(models.Account).all()
    manager = InviteStatusManager()
    
    fixes_applied = []
    accounts_fixed = 0
    
    for account in accounts:
        actual_count = manager.calculate_invites_sent(db, account)
        cached_count = account.invites_sent
        
        if actual_count != cached_count:
            fix_info = {
                "account_email": account.email,
                "old_count": str(cached_count),
                "new_count": str(actual_count),
                "difference": str(actual_count - cached_count)
            }
            
            if not dry_run:
                account.invites_sent = actual_count
                accounts_fixed += 1
                fix_info["status"] = "applied"
            else:
                fix_info["status"] = "preview"
            
            fixes_applied.append(fix_info)
    
    if not dry_run and accounts_fixed > 0:
        db.commit()
    
    return FixResult(
        accounts_fixed=accounts_fixed,
        total_accounts=len(accounts),
        fixes_applied=fixes_applied
    )

@router.get("/account/{email}", response_model=AccountConsistency)
async def get_account_consistency(
    email: str,
    db: Session = Depends(get_db)
):
    """获取指定账户的详细一致性信息"""
    account = db.query(models.Account).filter(models.Account.email == email).first()
    if not account:
        raise HTTPException(status_code=404, detail=f"账户 {email} 不存在")
    
    manager = InviteStatusManager()
    actual_count = manager.calculate_invites_sent(db, account)
    cached_count = account.invites_sent
    
    # 获取状态分布
    invites = db.query(models.Invite).filter(models.Invite.account_id == account.id).all()
    status_distribution = {"pending": 0, "accepted": 0, "expired": 0, "processed": 0}
    
    for invite in invites:
        status = manager.get_invite_status(invite).value
        status_distribution[status] += 1
    
    quota_total = 22
    quota_used = actual_count
    quota_available = max(0, quota_total - quota_used)
    
    return AccountConsistency(
        email=account.email,
        account_id=account.id,
        group_id=account.group_id,
        cached_count=cached_count,
        actual_count=actual_count,
        difference=cached_count - actual_count,
        is_consistent=actual_count == cached_count,
        quota_used=quota_used,
        quota_total=quota_total,
        quota_available=quota_available,
        status_distribution=status_distribution
    )

@router.post("/cleanup-expired")
async def cleanup_expired_invites(
    dry_run: bool = Query(False, description="是否只是预览"),
    account_email: Optional[str] = Query(None, description="指定账户，不指定则处理所有账户"),
    db: Session = Depends(get_db)
):
    """清理过期邀请"""
    import time
    
    now_ts = int(time.time())
    manager = InviteStatusManager()
    
    # 构建查询
    query = db.query(models.Invite).filter(
        models.Invite.expires_at.isnot(None),  # 排除手动用户
        models.Invite.expires_at < now_ts,
        models.Invite.cleaned == False
    )
    
    if account_email:
        account = db.query(models.Account).filter(models.Account.email == account_email).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"账户 {account_email} 不存在")
        query = query.filter(models.Invite.account_id == account.id)
    
    expired_invites = query.all()
    
    if not expired_invites:
        return {
            "message": "没有找到过期的邀请",
            "expired_count": 0,
            "dry_run": dry_run
        }
    
    processed_count = 0
    affected_accounts = set()
    
    if not dry_run:
        for invite in expired_invites:
            invite.cleaned = True
            affected_accounts.add(invite.account_id)
            processed_count += 1
        
        # 更新受影响账户的计数
        for account_id in affected_accounts:
            account = db.get(models.Account, account_id)
            if account:
                account.invites_sent = manager.calculate_invites_sent(db, account)
        
        db.commit()
    
    return {
        "message": f"{'预览' if dry_run else '已处理'} {len(expired_invites)} 个过期邀请",
        "expired_count": len(expired_invites),
        "processed_count": processed_count,
        "affected_accounts": len(affected_accounts),
        "dry_run": dry_run
    }

@router.get("/orphaned-cards")
async def check_orphaned_cards(db: Session = Depends(get_db)):
    """检查孤立的卡密关联"""
    # 查找引用了不存在卡密的邀请
    orphaned_invites = (
        db.query(models.Invite)
        .filter(models.Invite.card_id.isnot(None))
        .filter(models.Invite.expires_at.isnot(None))  # 排除手动用户
        .outerjoin(models.Card, models.Invite.card_id == models.Card.id)
        .filter(models.Card.id.is_(None))
        .all()
    )
    
    # 查找从未被使用的卡密
    unused_cards = (
        db.query(models.Card)
        .outerjoin(models.Invite, models.Card.id == models.Invite.card_id)
        .filter(models.Invite.id.is_(None))
        .all()
    )
    
    return {
        "orphaned_invites_count": len(orphaned_invites),
        "orphaned_invites": [
            {
                "invite_id": invite.id,
                "email": invite.email,
                "card_id": invite.card_id,
                "account_email": invite.account.email
            }
            for invite in orphaned_invites
        ],
        "unused_cards_count": len(unused_cards),
        "unused_cards": [
            {
                "card_id": card.id,
                "code": card.code,
                "validity_days": card.validity_days,
                "created_at": datetime.fromtimestamp(card.created_at).strftime('%Y-%m-%d %H:%M:%S')
            }
            for card in unused_cards
        ]
    }