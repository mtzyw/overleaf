# invite_status_manager.py
"""
邀请状态管理工具类
重新定义字段语义，提供统一的状态判断和管理逻辑
"""

import time
from enum import Enum
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
import models


class InviteStatus(Enum):
    """邀请状态枚举"""
    PENDING = "pending"      # 已发送，等待接受
    ACCEPTED = "accepted"    # 已接受，成员活跃  
    EXPIRED = "expired"      # 已过期，待清理
    PROCESSED = "processed"  # 已处理（删除/撤销/过期清理）


class InviteStatusManager:
    """邀请状态管理器"""
    
    @staticmethod
    def get_invite_status(invite: models.Invite) -> InviteStatus:
        """
        根据邀请记录判断其当前状态
        
        判断逻辑：
        1. cleaned=True -> PROCESSED (已处理)
        2. email_id存在 -> ACCEPTED (已接受)  
        3. 过期且未清理 -> EXPIRED (待处理)
        4. 其他 -> PENDING (等待接受)
        """
        if invite.cleaned:
            return InviteStatus.PROCESSED
        elif invite.email_id:
            return InviteStatus.ACCEPTED
        elif invite.expires_at is not None and invite.expires_at < int(time.time()):
            return InviteStatus.EXPIRED
        else:
            return InviteStatus.PENDING
    
    @staticmethod
    def is_active_invite(invite: models.Invite) -> bool:
        """判断邀请是否为活跃状态（占用quota）"""
        status = InviteStatusManager.get_invite_status(invite)
        return status in [InviteStatus.PENDING, InviteStatus.ACCEPTED]
    
    @staticmethod
    def is_removable(invite: models.Invite) -> bool:
        """判断邀请是否可以被删除（已被接受的成员）"""
        return invite.email_id is not None and not invite.cleaned
    
    @staticmethod
    def is_revokable(invite: models.Invite) -> bool:
        """判断邀请是否可以被撤销（未被接受的邀请）"""
        return invite.email_id is None and not invite.cleaned
    
    @staticmethod
    def calculate_invites_sent(db: Session, account: models.Account) -> int:
        """
        重新计算账户的邀请发送数量
        只统计每个邮箱的最新有效邀请，避免重复计数
        """
        import time
        now_ts = int(time.time())
        
        from sqlalchemy import func, and_
        
        # 查找该账户的所有邀请，按邮箱分组，只取每个邮箱的最新记录
        latest_invites_subquery = (
            db.query(
                models.Invite.email,
                func.max(models.Invite.created_at).label('latest_created_at')
            )
            .filter(models.Invite.account_id == account.id)
            .group_by(models.Invite.email)
            .subquery()
        )
        
        # 获取每个邮箱的最新邀请记录
        latest_invites = (
            db.query(models.Invite)
            .join(
                latest_invites_subquery,
                and_(
                    models.Invite.email == latest_invites_subquery.c.email,
                    models.Invite.created_at == latest_invites_subquery.c.latest_created_at
                )
            )
            .filter(models.Invite.account_id == account.id)
            .all()
        )
        
        # 统计真正占用Overleaf名额的最新邀请（排除已清理的）
        active_count = 0
        for invite in latest_invites:
            # 跳过已清理的记录
            if invite.cleaned:
                continue
                
            # 已接受的成员（无论是否过期，因为还在组里）
            if invite.email_id:
                active_count += 1
            # 未接受但未过期的邀请（占用邀请名额）
            elif invite.expires_at is None or invite.expires_at > now_ts:
                active_count += 1
        
        return active_count
    
    @staticmethod 
    def sync_account_invites_count(db: Session, account: models.Account) -> models.Account:
        """
        同步账户的邀请计数到数据库实际值
        """
        real_count = InviteStatusManager.calculate_invites_sent(db, account)
        if account.invites_sent != real_count:
            old_count = account.invites_sent
            account.invites_sent = real_count
            account.updated_at = int(time.time())
            db.commit()
            db.refresh(account)
            print(f"账户 {account.email} 邀请计数修正: {old_count} -> {real_count}")
        return account
    
    @staticmethod
    def get_account_status_summary(db: Session, account: models.Account) -> Dict[str, Any]:
        """获取账户的详细状态摘要"""
        invites = (
            db.query(models.Invite)
            .filter(models.Invite.account_id == account.id)
            .all()
        )
        
        status_counts = {status.value: 0 for status in InviteStatus}
        for invite in invites:
            status = InviteStatusManager.get_invite_status(invite)
            status_counts[status.value] += 1
            
        real_active_count = status_counts[InviteStatus.PENDING.value] + status_counts[InviteStatus.ACCEPTED.value]
        
        return {
            "account_email": account.email,
            "group_id": account.group_id,
            "invites_sent_cached": account.invites_sent,
            "invites_sent_real": real_active_count,
            "count_mismatch": account.invites_sent != real_active_count,
            "max_invites": account.max_invites,
            "available_quota": account.max_invites - real_active_count,
            "status_breakdown": status_counts,
            "total_invites": len(invites)
        }
    
    @staticmethod
    def mark_invite_processed(db: Session, invite: models.Invite, 
                            reason: str = "processed") -> models.Invite:
        """
        标记邀请为已处理状态
        """
        invite.cleaned = True
        # 更新result字段记录处理原因和时间
        import json
        try:
            result_data = json.loads(invite.result) if invite.result else {}
        except:
            result_data = {"original_result": invite.result}
            
        result_data.update({
            "processed_at": int(time.time()),
            "processed_reason": reason
        })
        invite.result = json.dumps(result_data, ensure_ascii=False)
        
        db.add(invite)
        db.commit()
        db.refresh(invite)
        return invite
    
    @staticmethod
    def batch_cleanup_expired(db: Session, limit: int = 100, delete_records: bool = True) -> Dict[str, int]:
        """
        批量清理过期邀请
        
        Args:
            db: 数据库会话
            limit: 单次处理的最大数量
            delete_records: 是否真正删除记录（True）还是只标记（False）
            
        返回处理统计信息
        """
        now_ts = int(time.time())
        
        # 查找过期且未处理的邀请（排除手动添加的用户）
        expired_invites = (
            db.query(models.Invite)
            .filter(
                models.Invite.expires_at.isnot(None),
                models.Invite.expires_at < now_ts,
                models.Invite.cleaned.is_(False)
            )
            .limit(limit)
            .all()
        )
        
        stats = {
            "total_found": len(expired_invites),
            "accepted_removed": 0,  # 已接受的成员被删除
            "pending_revoked": 0,   # 未接受的邀请被撤销
            "deleted_records": 0,   # 真正删除的记录数
            "marked_processed": 0,  # 标记为已处理的记录数
            "errors": 0
        }
        
        # 批量处理过期邀请
        for invite in expired_invites:
            try:
                if delete_records:
                    # 真正删除记录
                    db.delete(invite)
                    if invite.email_id:
                        stats["accepted_removed"] += 1
                    else:
                        stats["pending_revoked"] += 1
                    stats["deleted_records"] += 1
                else:
                    # 标记删除（兼容性保留）
                    InviteStatusManager.mark_invite_processed(db, invite, "expired")
                    stats["marked_processed"] += 1
                    
            except Exception as e:
                print(f"处理邀请ID {invite.id} 时出错: {e}")
                stats["errors"] += 1
        
        # 提交事务
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"批量清理提交失败: {e}")
            stats["errors"] += len(expired_invites)
            stats["deleted_records"] = 0
            stats["marked_processed"] = 0
        
        return stats
    
    @staticmethod
    def validate_data_consistency(db: Session) -> List[Dict[str, Any]]:
        """
        验证数据一致性，返回发现的问题列表
        """
        issues = []
        
        # 检查所有账户的计数一致性
        accounts = db.query(models.Account).all()
        for account in accounts:
            real_count = InviteStatusManager.calculate_invites_sent(db, account)
            if account.invites_sent != real_count:
                issues.append({
                    "type": "count_mismatch",
                    "account_email": account.email,
                    "cached_count": account.invites_sent,
                    "real_count": real_count,
                    "difference": account.invites_sent - real_count
                })
        
        # 检查邀请记录的逻辑一致性
        invites = db.query(models.Invite).all()
        for invite in invites:
            # 检查已清理但仍有email_id的记录
            if invite.cleaned and invite.email_id and invite.expires_at > int(time.time()):
                issues.append({
                    "type": "cleaned_but_active",
                    "invite_id": invite.id,
                    "email": invite.email,
                    "description": "邀请被标记为已清理，但成员可能仍然活跃"
                })
            
            # 检查过期但未清理的已接受邀请
            if (not invite.cleaned and invite.email_id and 
                invite.expires_at < int(time.time())):
                issues.append({
                    "type": "expired_accepted_not_cleaned",
                    "invite_id": invite.id,
                    "email": invite.email,
                    "description": "已接受的邀请已过期但未被清理"
                })
        
        return issues


class TransactionManager:
    """事务管理器，确保相关操作的原子性"""
    
    @staticmethod
    async def safe_remove_member(db: Session, invite: models.Invite, 
                          remove_func, delete_record: bool = True) -> Dict[str, Any]:
        """
        安全的成员删除操作，包含事务管理
        
        Args:
            db: 数据库会话
            invite: 邀请记录
            remove_func: 删除函数
            delete_record: 是否真正删除记录（True）还是只标记（False）
        """
        if not InviteStatusManager.is_removable(invite):
            return {
                "success": False,
                "reason": "invite_not_removable",
                "message": "邀请不可删除（未被接受或已被处理）"
            }
        
        account = db.get(models.Account, invite.account_id)
        if not account:
            return {
                "success": False,
                "reason": "account_not_found", 
                "message": "找不到关联的账户"
            }
        
        try:
            # 1. 调用删除函数
            result = await remove_func()
            
            # 2. 更新数据库状态（在一个事务中）
            if delete_record:
                # 真正删除记录
                db.delete(invite)
            else:
                # 标记删除（兼容性保留）
                InviteStatusManager.mark_invite_processed(db, invite, "member_removed")
            
            # 3. 提交事务
            db.commit()
            
            # 4. 同步账户计数（在删除后重新计算）
            InviteStatusManager.sync_account_invites_count(db, account)
            
            return {
                "success": True,
                "result": result,
                "message": result.get("message", "成员删除成功")
            }
            
        except Exception as e:
            db.rollback()
            return {
                "success": False,
                "reason": "operation_failed",
                "message": f"删除操作失败: {str(e)}"
            }