#!/usr/bin/env python3
"""
自动清理过期成员脚本 - 每30分钟执行一次
"""

import sys
import os
import time
import logging
from datetime import datetime

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models

# 配置日志 - 只输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def cleanup_expired_members():
    """清理过期成员"""
    db = SessionLocal()
    manager = InviteStatusManager()
    
    try:
        logger.info("🗑️ 开始清理过期成员...")
        
        now_ts = int(time.time())
        
        # 查找过期的邀请（排除手动用户）
        expired_invites = (
            db.query(models.Invite)
            .filter(models.Invite.expires_at.isnot(None))  # 排除手动用户
            .filter(models.Invite.expires_at < now_ts)
            .filter(models.Invite.cleaned == False)
            .all()
        )
        
        if not expired_invites:
            logger.info("✅ 没有过期成员需要清理")
            return {
                "success": True,
                "expired_count": 0,
                "processed_count": 0,
                "message": "没有过期成员"
            }
        
        # 按账户分组统计
        by_account = {}
        for invite in expired_invites:
            account_email = invite.account.email
            if account_email not in by_account:
                by_account[account_email] = []
            by_account[account_email].append({
                "email": invite.email,
                "expired_days": (now_ts - invite.expires_at) // 86400
            })
        
        # 执行清理
        processed_count = 0
        affected_accounts = set()
        
        for invite in expired_invites:
            invite.cleaned = True
            processed_count += 1
            affected_accounts.add(invite.account_id)
        
        # 更新受影响账户的计数
        for account_id in affected_accounts:
            account = db.get(models.Account, account_id)
            if account:
                account.invites_sent = manager.calculate_invites_sent(db, account)
        
        db.commit()
        
        logger.info(f"✅ 已清理 {processed_count} 个过期成员，影响 {len(affected_accounts)} 个账户")
        
        # 详细统计
        for account_email, members in by_account.items():
            logger.info(f"  {account_email}: {len(members)} 个过期成员")
        
        return {
            "success": True,
            "expired_count": len(expired_invites),
            "processed_count": processed_count,
            "affected_accounts": len(affected_accounts),
            "details": by_account
        }
        
    except Exception as e:
        logger.error(f"❌ 清理失败: {e}")
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("自动清理过期成员任务")
    logger.info("=" * 50)
    
    result = cleanup_expired_members()
    
    if result["success"]:
        logger.info(f"🎉 清理完成: 处理了 {result['processed_count']} 个过期成员")
    else:
        logger.error(f"💥 清理失败: {result['error']}")
        sys.exit(1)