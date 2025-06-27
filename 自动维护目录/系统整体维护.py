#!/usr/bin/env python3
"""
系统整体维护脚本 - 每天执行一次
包含: 完整同步、数据一致性检查、计数修复、系统健康报告
"""

import sys
import os
import asyncio
import time
import logging
import json
from datetime import datetime

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models
from overleaf_utils import get_tokens, get_captcha_token, perform_login, refresh_session, get_new_csrf
import requests
import re
import html

# 配置日志 - 只输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class SystemMaintenance:
    """系统整体维护管理器"""
    
    def __init__(self):
        self.db = SessionLocal()
        self.status_manager = InviteStatusManager()
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    async def get_overleaf_members(self, account: models.Account):
        """获取Overleaf群组成员"""
        session = requests.Session()
        
        # 使用现有token或重新登录
        if account.session_cookie and account.csrf_token:
            session.cookies.set(
                "overleaf_session2", account.session_cookie,
                domain=".overleaf.com", path="/"
            )
        else:
            # 重新登录
            logger.info(f"账户 {account.email} 需要重新登录...")
            csrf0, sess0 = await get_tokens()
            captcha = get_captcha_token()
            session = await asyncio.to_thread(
                perform_login, csrf0, sess0,
                account.email, account.password, captcha
            )
            new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
            csrf_token = await asyncio.to_thread(get_new_csrf, session, account.group_id)
            
            # 更新数据库中的token
            account.session_cookie = new_sess
            account.csrf_token = csrf_token
            self.db.commit()
        
        # 获取群组成员页面
        members_url = f"https://www.overleaf.com/manage/groups/{account.group_id}/members"
        resp = session.get(members_url, headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "zh-CN,zh;q=0.9",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        
        if resp.status_code != 200:
            raise Exception(f"获取成员数据失败: {resp.status_code}")
        
        # 解析HTML中的ol-users meta标签
        html_content = resp.text
        meta_pattern = r'<meta\s+name="ol-users"[^>]*content="([^"]*)"'
        match = re.search(meta_pattern, html_content)
        
        if not match:
            raise Exception("未找到ol-users meta标签")
        
        users_content = html.unescape(match.group(1))
        users_data = json.loads(users_content)
        
        # 转换为统一格式
        members = []
        for user in users_data:
            members.append({
                "email": user.get("email"),
                "user_id": user.get("_id"),
                "status": "accepted" if user.get("_id") else "pending"
            })
        
        return members
    
    async def sync_account_with_overleaf(self, account: models.Account):
        """与Overleaf同步单个账户"""
        try:
            logger.info(f"🔄 同步账户: {account.email}")
            
            # 1. 获取Overleaf真实数据
            overleaf_members = await self.get_overleaf_members(account)
            overleaf_count = len(overleaf_members)
            
            # 2. 分析数据库中的邀请记录
            db_invites = (
                self.db.query(models.Invite)
                .filter(models.Invite.account_id == account.id)
                .filter(models.Invite.cleaned == False)
                .all()
            )
            
            db_count = len(db_invites)
            logger.info(f"  数据库记录: {db_count}, Overleaf实际: {overleaf_count}")
            
            # 3. 创建邮箱到Overleaf状态的映射
            overleaf_status = {}
            for member in overleaf_members:
                overleaf_status[member["email"]] = {
                    "user_id": member["user_id"],
                    "status": member["status"]
                }
            
            # 4. 检查数据库外用户（只在Overleaf中存在）
            # 检查所有数据库记录，不仅仅是未清理的
            all_db_invites = (
                self.db.query(models.Invite)
                .filter(models.Invite.account_id == account.id)
                .all()
            )
            all_db_emails = {invite.email for invite in all_db_invites}
            database_external_users = []
            
            for email, ol_data in overleaf_status.items():
                if email not in all_db_emails:
                    database_external_users.append({
                        "email": email,
                        "user_id": ol_data["user_id"],
                        "status": ol_data["status"]
                    })
            
            # 5. 分析需要修复的记录
            updates_applied = 0
            for invite in db_invites:
                if invite.email in overleaf_status:
                    # 在Overleaf中存在
                    ol_data = overleaf_status[invite.email]
                    
                    if ol_data["status"] == "accepted" and not invite.email_id:
                        # 数据库显示未接受，但Overleaf显示已接受
                        invite.email_id = ol_data["user_id"]
                        updates_applied += 1
                        logger.info(f"    ✅ 更新email_id: {invite.email}")
                    
                    if invite.cleaned:
                        # 数据库显示已清理，但Overleaf中还存在
                        invite.cleaned = False
                        updates_applied += 1
                        logger.info(f"    ✅ 取消清理标记: {invite.email}")
                        
                else:
                    # 在Overleaf中不存在
                    if not invite.cleaned:
                        # 数据库显示未清理，但Overleaf中不存在
                        invite.cleaned = True
                        updates_applied += 1
                        logger.info(f"    ✅ 标记为已清理: {invite.email}")
            
            # 6. 创建数据库外用户记录
            external_users_created = 0
            if database_external_users:
                logger.info(f"  发现数据库外用户: {len(database_external_users)}个")
                
                for user in database_external_users:
                    # 创建完整的result信息
                    result_info = {
                        "source": "daily_sync_maintenance",
                        "sync_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "account_manager": account.email,
                        "overleaf_status": user['status'],
                        "overleaf_user_id": user['user_id'],
                        "note": "系统自动检测的数据库外用户，需要联系客户确认",
                        "action_required": "请设置过期时间并关联正确的卡密",
                        "warning": "设置过期时间后，到期会被正常清理删除"
                    }
                    
                    new_invite = models.Invite(
                        account_id=account.id,
                        card_id=None,  # 手动添加的用户没有卡密
                        email=user['email'],
                        email_id=user['user_id'] if user['status'] == 'accepted' else None,
                        expires_at=None,  # 关键：不设置过期时间，标记为手动添加
                        success=True,  # 已经在Overleaf中存在
                        result=json.dumps(result_info, ensure_ascii=False),
                        created_at=int(time.time()),
                        cleaned=False
                    )
                    self.db.add(new_invite)
                    external_users_created += 1
                    logger.info(f"    ✅ 创建手动用户: {user['email']}")
            
            if updates_applied > 0 or external_users_created > 0:
                self.db.commit()
            
            # 7. 修正账户计数 - 基于Overleaf真实数据
            account.invites_sent = overleaf_count
            self.db.commit()
            
            logger.info(f"  ✅ 同步完成: 修复{updates_applied}条，新增{external_users_created}条，计数{account.invites_sent}")
            
            return {
                "account_email": account.email,
                "success": True,
                "overleaf_count": overleaf_count,
                "updates_applied": updates_applied,
                "external_users_created": external_users_created,
                "final_count": account.invites_sent
            }
            
        except Exception as e:
            logger.error(f"  ❌ 同步失败: {e}")
            return {
                "account_email": account.email,
                "success": False,
                "error": str(e)
            }
    
    def cleanup_expired_invites(self):
        """清理过期邀请"""
        logger.info("🗑️ 清理过期邀请...")
        
        now_ts = int(time.time())
        
        # 查找过期的邀请（排除手动用户）
        expired_invites = (
            self.db.query(models.Invite)
            .filter(models.Invite.expires_at.isnot(None))  # 排除手动用户
            .filter(models.Invite.expires_at < now_ts)
            .filter(models.Invite.cleaned == False)
            .all()
        )
        
        if not expired_invites:
            logger.info("  ✅ 没有过期邀请需要清理")
            return 0
        
        processed_count = 0
        affected_accounts = set()
        
        for invite in expired_invites:
            invite.cleaned = True
            processed_count += 1
            affected_accounts.add(invite.account_id)
        
        # 更新受影响账户的计数
        for account_id in affected_accounts:
            account = self.db.get(models.Account, account_id)
            if account:
                account.invites_sent = self.status_manager.calculate_invites_sent(self.db, account)
        
        self.db.commit()
        logger.info(f"  ✅ 已清理 {processed_count} 个过期邀请，影响 {len(affected_accounts)} 个账户")
        
        return processed_count
    
    def fix_account_counts(self):
        """修复账户计数"""
        logger.info("🔧 修复账户计数...")
        
        accounts = self.db.query(models.Account).all()
        accounts_fixed = 0
        
        for account in accounts:
            actual_count = self.status_manager.calculate_invites_sent(self.db, account)
            cached_count = account.invites_sent
            
            if actual_count != cached_count:
                account.invites_sent = actual_count
                accounts_fixed += 1
                logger.info(f"  ✅ 修复 {account.email}: {cached_count} -> {actual_count}")
        
        if accounts_fixed > 0:
            self.db.commit()
            logger.info(f"  ✅ 已修复 {accounts_fixed} 个账户的计数")
        else:
            logger.info("  ✅ 所有账户计数都正确")
        
        return accounts_fixed
    
    def generate_system_report(self):
        """生成系统健康报告"""
        logger.info("📊 生成系统健康报告...")
        
        accounts = self.db.query(models.Account).all()
        total_invites = 0
        total_quota = 0
        inconsistent_accounts = 0
        
        # 按状态统计
        global_stats = {"pending": 0, "accepted": 0, "expired": 0, "processed": 0}
        
        for account in accounts:
            actual_count = self.status_manager.calculate_invites_sent(self.db, account)
            cached_count = account.invites_sent
            
            if actual_count != cached_count:
                inconsistent_accounts += 1
            
            total_invites += actual_count
            total_quota += 22  # 假设每个账户配额22
            
            # 统计该账户的状态分布
            invites = self.db.query(models.Invite).filter(models.Invite.account_id == account.id).all()
            for invite in invites:
                status = self.status_manager.get_invite_status(invite).value
                global_stats[status] += 1
        
        # 统计手动用户
        manual_users_count = (
            self.db.query(models.Invite)
            .filter(models.Invite.expires_at.is_(None))
            .filter(models.Invite.cleaned == False)
            .count()
        )
        
        # 统计过期邀请
        now_ts = int(time.time())
        expired_count = (
            self.db.query(models.Invite)
            .filter(models.Invite.expires_at.isnot(None))
            .filter(models.Invite.expires_at < now_ts)
            .filter(models.Invite.cleaned == False)
            .count()
        )
        
        report = {
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "total_accounts": len(accounts),
            "total_invites": total_invites,
            "total_quota": total_quota,
            "quota_utilization": round(total_invites / total_quota * 100, 1) if total_quota > 0 else 0,
            "inconsistent_accounts": inconsistent_accounts,
            "global_stats": global_stats,
            "manual_users_count": manual_users_count,
            "expired_invites_count": expired_count,
            "system_health": "健康" if inconsistent_accounts == 0 and expired_count == 0 else "需要维护"
        }
        
        logger.info(f"📊 系统状态: {report['system_health']}")
        logger.info(f"📊 配额使用率: {report['quota_utilization']}%")
        logger.info(f"📊 数据不一致账户: {inconsistent_accounts}个")
        logger.info(f"📊 手动用户: {manual_users_count}个")
        logger.info(f"📊 过期邀请: {expired_count}个")
        
        return report
    
    async def run_full_maintenance(self):
        """运行完整的系统维护"""
        logger.info("🚀 开始系统整体维护...")
        
        # 1. 生成维护前报告
        logger.info("📋 步骤1: 生成维护前报告")
        pre_report = self.generate_system_report()
        
        # 2. 同步所有账户
        logger.info("🔄 步骤2: 与Overleaf同步所有账户")
        accounts = self.db.query(models.Account).all()
        sync_results = []
        
        for i, account in enumerate(accounts, 1):
            logger.info(f"📊 进度: {i}/{len(accounts)}")
            result = await self.sync_account_with_overleaf(account)
            sync_results.append(result)
            
            # 避免请求过快
            await asyncio.sleep(2)
        
        # 3. 清理过期邀请
        logger.info("🗑️ 步骤3: 清理过期邀请")
        expired_cleaned = self.cleanup_expired_invites()
        
        # 4. 修复账户计数（已在步骤2中基于Overleaf真实数据完成）
        logger.info("🔧 步骤4: 跳过账户计数修复（已在同步中完成）")
        accounts_fixed = 0
        
        # 5. 生成维护后报告
        logger.info("📋 步骤5: 生成维护后报告")
        post_report = self.generate_system_report()
        
        # 生成总结
        successful_syncs = len([r for r in sync_results if r["success"]])
        total_external_users = sum(r.get("external_users_created", 0) for r in sync_results if r["success"])
        total_updates = sum(r.get("updates_applied", 0) for r in sync_results if r["success"])
        
        logger.info("=" * 60)
        logger.info("🎉 系统整体维护完成")
        logger.info("=" * 60)
        logger.info(f"📊 账户同步: {successful_syncs}/{len(accounts)} 成功")
        logger.info(f"📊 数据修复: {total_updates} 条记录")
        logger.info(f"📊 新增手动用户: {total_external_users} 个")
        logger.info(f"📊 过期清理: {expired_cleaned} 条记录")
        logger.info(f"📊 计数修复: {accounts_fixed} 个账户")
        logger.info(f"📊 系统状态: {pre_report['system_health']} -> {post_report['system_health']}")
        
        return {
            "pre_report": pre_report,
            "post_report": post_report,
            "sync_results": sync_results,
            "expired_cleaned": expired_cleaned,
            "accounts_fixed": accounts_fixed,
            "summary": {
                "successful_syncs": successful_syncs,
                "total_external_users": total_external_users,
                "total_updates": total_updates
            }
        }

async def main():
    """主函数"""
    logger.info("=" * 80)
    logger.info("系统整体维护任务")
    logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    
    maintenance = SystemMaintenance()
    
    try:
        result = await maintenance.run_full_maintenance()
        logger.info("🎉 系统整体维护任务完成")
        return result
        
    except Exception as e:
        logger.error(f"💥 维护任务失败: {e}")
        sys.exit(1)
    finally:
        maintenance.db.close()

if __name__ == "__main__":
    asyncio.run(main())