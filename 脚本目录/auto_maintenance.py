#!/usr/bin/env python3
"""
自动维护脚本 - 定时更新email_id和检测过期删除
支持定时任务和手动执行
"""

import asyncio
import time
import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models
from overleaf_utils import get_tokens, get_captcha_token, perform_login, refresh_session, get_new_csrf
import requests
import re
import html

# 配置日志 - 只输出到控制台，不生成日志文件
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # 只保留控制台输出
    ]
)
logger = logging.getLogger(__name__)

class AutoMaintenanceManager:
    """自动维护管理器"""
    
    def __init__(self):
        self.db = SessionLocal()
        self.status_manager = InviteStatusManager()
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    async def update_all_email_ids(self) -> Dict:
        """更新所有账户的email_id"""
        logger.info("开始更新所有账户的email_id...")
        
        accounts = self.db.query(models.Account).all()
        results = {
            "total_accounts": len(accounts),
            "success_accounts": 0,
            "failed_accounts": 0,
            "total_updated": 0,
            "account_results": []
        }
        
        for account in accounts:
            try:
                logger.info(f"处理账户: {account.email}")
                account_result = await self._update_account_email_ids(account)
                results["account_results"].append(account_result)
                
                if account_result["success"]:
                    results["success_accounts"] += 1
                    results["total_updated"] += account_result["updated_count"]
                else:
                    results["failed_accounts"] += 1
                    
                # 避免请求过快
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"处理账户 {account.email} 时发生错误: {e}")
                results["failed_accounts"] += 1
                results["account_results"].append({
                    "account_email": account.email,
                    "success": False,
                    "error": str(e),
                    "updated_count": 0
                })
        
        logger.info(f"email_id更新完成: 成功{results['success_accounts']}个，失败{results['failed_accounts']}个，总共更新{results['total_updated']}条记录")
        return results
    
    async def _update_account_email_ids(self, account: models.Account) -> Dict:
        """更新单个账户的email_id"""
        try:
            # 获取Overleaf群组成员数据
            overleaf_members = await self._get_overleaf_members(account)
            
            # 构建email到user_id的映射
            email_to_user_id = {}
            for member in overleaf_members:
                if member.get("email") and member.get("user_id"):
                    email_to_user_id[member["email"]] = member["user_id"]
            
            # 查找该账户下需要更新的邀请记录
            invites_to_update = (
                self.db.query(models.Invite)
                .filter(models.Invite.account_id == account.id)
                .filter(models.Invite.email_id.is_(None))  # 只更新没有email_id的记录
                .filter(models.Invite.email.in_(list(email_to_user_id.keys())))  # 只更新在Overleaf中存在的
                .all()
            )
            
            updated_count = 0
            updated_emails = []
            
            for invite in invites_to_update:
                if invite.email in email_to_user_id:
                    invite.email_id = email_to_user_id[invite.email]
                    updated_count += 1
                    updated_emails.append(invite.email)
            
            if updated_count > 0:
                self.db.commit()
                logger.info(f"账户 {account.email}: 更新了 {updated_count} 个email_id")
            
            return {
                "account_email": account.email,
                "success": True,
                "updated_count": updated_count,
                "updated_emails": updated_emails,
                "overleaf_total_members": len(overleaf_members)
            }
            
        except Exception as e:
            logger.error(f"更新账户 {account.email} 的email_id失败: {e}")
            return {
                "account_email": account.email,
                "success": False,
                "error": str(e),
                "updated_count": 0
            }
    
    async def _get_overleaf_members(self, account: models.Account) -> List[Dict]:
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
    
    def cleanup_expired_invites(self, dry_run: bool = False) -> Dict:
        """清理过期邀请"""
        logger.info(f"开始清理过期邀请 (dry_run: {dry_run})...")
        
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
            logger.info("没有找到过期的邀请")
            return {
                "expired_count": 0,
                "processed_count": 0,
                "dry_run": dry_run,
                "affected_accounts": {}
            }
        
        # 按账户分组
        by_account = {}
        for invite in expired_invites:
            account_email = invite.account.email
            if account_email not in by_account:
                by_account[account_email] = []
            by_account[account_email].append({
                "email": invite.email,
                "expired_days": (now_ts - invite.expires_at) // 86400,
                "invite_id": invite.id
            })
        
        processed_count = 0
        affected_accounts = set()
        
        if not dry_run:
            # 实际执行清理
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
            logger.info(f"已清理 {processed_count} 个过期邀请，影响 {len(affected_accounts)} 个账户")
        else:
            logger.info(f"预览模式: 发现 {len(expired_invites)} 个过期邀请")
        
        return {
            "expired_count": len(expired_invites),
            "processed_count": processed_count,
            "dry_run": dry_run,
            "affected_accounts": by_account
        }
    
    def fix_account_counts(self, dry_run: bool = False) -> Dict:
        """修复账户计数"""
        logger.info(f"开始修复账户计数 (dry_run: {dry_run})...")
        
        accounts = self.db.query(models.Account).all()
        fixes_applied = []
        accounts_fixed = 0
        
        for account in accounts:
            actual_count = self.status_manager.calculate_invites_sent(self.db, account)
            cached_count = account.invites_sent
            
            if actual_count != cached_count:
                fix_info = {
                    "account_email": account.email,
                    "old_count": cached_count,
                    "new_count": actual_count,
                    "difference": actual_count - cached_count
                }
                
                if not dry_run:
                    account.invites_sent = actual_count
                    accounts_fixed += 1
                    fix_info["status"] = "applied"
                    logger.info(f"修复账户 {account.email}: {cached_count} -> {actual_count}")
                else:
                    fix_info["status"] = "preview"
                
                fixes_applied.append(fix_info)
        
        if not dry_run and accounts_fixed > 0:
            self.db.commit()
            logger.info(f"已修复 {accounts_fixed} 个账户的计数问题")
        
        return {
            "accounts_fixed": accounts_fixed,
            "total_accounts": len(accounts),
            "fixes_applied": fixes_applied,
            "dry_run": dry_run
        }
    
    def generate_report(self) -> Dict:
        """生成系统状态报告"""
        logger.info("生成系统状态报告...")
        
        accounts = self.db.query(models.Account).all()
        total_invites = 0
        total_quota = 0
        inconsistent_accounts = []
        
        # 按状态统计
        global_stats = {"pending": 0, "accepted": 0, "expired": 0, "processed": 0}
        
        for account in accounts:
            actual_count = self.status_manager.calculate_invites_sent(self.db, account)
            cached_count = account.invites_sent
            
            if actual_count != cached_count:
                inconsistent_accounts.append({
                    "email": account.email,
                    "cached": cached_count,
                    "actual": actual_count,
                    "difference": cached_count - actual_count
                })
            
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
            "inconsistent_accounts": len(inconsistent_accounts),
            "inconsistent_details": inconsistent_accounts,
            "global_stats": global_stats,
            "manual_users_count": manual_users_count,
            "expired_invites_count": expired_count,
            "system_health": "健康" if len(inconsistent_accounts) == 0 and expired_count == 0 else "需要维护"
        }
        
        logger.info(f"系统状态: {report['system_health']}, 配额使用率: {report['quota_utilization']}%")
        return report


async def run_full_maintenance(dry_run: bool = False):
    """运行完整的维护流程"""
    manager = AutoMaintenanceManager()
    
    try:
        logger.info("="*60)
        logger.info(f"开始自动维护流程 (dry_run: {dry_run})")
        logger.info("="*60)
        
        # 1. 生成维护前报告
        logger.info("步骤1: 生成维护前报告")
        pre_report = manager.generate_report()
        logger.info(f"维护前系统状态: {pre_report['system_health']}")
        
        # 2. 更新所有email_id
        logger.info("步骤2: 更新email_id")
        email_update_result = await manager.update_all_email_ids()
        
        # 3. 清理过期邀请
        logger.info("步骤3: 清理过期邀请")
        cleanup_result = manager.cleanup_expired_invites(dry_run)
        
        # 4. 修复账户计数
        logger.info("步骤4: 修复账户计数")
        fix_result = manager.fix_account_counts(dry_run)
        
        # 5. 生成维护后报告
        logger.info("步骤5: 生成维护后报告")
        post_report = manager.generate_report()
        
        # 生成总结
        summary = {
            "maintenance_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "dry_run": dry_run,
            "pre_maintenance": {
                "system_health": pre_report['system_health'],
                "total_invites": pre_report['total_invites'],
                "inconsistent_accounts": pre_report['inconsistent_accounts'],
                "expired_invites": pre_report['expired_invites_count']
            },
            "actions_performed": {
                "email_ids_updated": email_update_result['total_updated'],
                "expired_cleaned": cleanup_result['processed_count'],
                "accounts_fixed": fix_result['accounts_fixed']
            },
            "post_maintenance": {
                "system_health": post_report['system_health'],
                "total_invites": post_report['total_invites'],
                "inconsistent_accounts": post_report['inconsistent_accounts'],
                "expired_invites": post_report['expired_invites_count']
            }
        }
        
        logger.info("="*60)
        logger.info("维护流程完成")
        logger.info("="*60)
        logger.info(f"email_id更新: {summary['actions_performed']['email_ids_updated']}条")
        logger.info(f"过期清理: {summary['actions_performed']['expired_cleaned']}条")
        logger.info(f"计数修复: {summary['actions_performed']['accounts_fixed']}个账户")
        logger.info(f"系统状态: {summary['pre_maintenance']['system_health']} -> {summary['post_maintenance']['system_health']}")
        
        # 不再保存详细报告文件，节省存储空间
        return summary
        
    except Exception as e:
        logger.error(f"维护流程发生错误: {e}")
        raise
    finally:
        manager.db.close()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='自动维护脚本')
    parser.add_argument('command', choices=['update-emails', 'cleanup-expired', 'fix-counts', 'report', 'full'], 
                       help='执行的命令')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不实际执行修改')
    parser.add_argument('--quiet', action='store_true', help='安静模式，只输出错误')
    
    args = parser.parse_args()
    
    if args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    
    manager = AutoMaintenanceManager()
    
    try:
        if args.command == 'update-emails':
            result = asyncio.run(manager.update_all_email_ids())
            print(f"更新完成: 成功{result['success_accounts']}个账户，更新{result['total_updated']}条记录")
            
        elif args.command == 'cleanup-expired':
            result = manager.cleanup_expired_invites(args.dry_run)
            print(f"清理{'预览' if args.dry_run else '完成'}: {result['expired_count']}个过期邀请")
            
        elif args.command == 'fix-counts':
            result = manager.fix_account_counts(args.dry_run)
            print(f"修复{'预览' if args.dry_run else '完成'}: {result['accounts_fixed']}个账户")
            
        elif args.command == 'report':
            result = manager.generate_report()
            print(f"系统状态: {result['system_health']}")
            print(f"配额使用率: {result['quota_utilization']}%")
            print(f"数据不一致账户: {result['inconsistent_accounts']}个")
            print(f"过期邀请: {result['expired_invites_count']}个")
            print(f"手动用户: {result['manual_users_count']}个")
            
        elif args.command == 'full':
            result = asyncio.run(run_full_maintenance(args.dry_run))
            print("完整维护流程执行完成")
            
    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)
    finally:
        manager.db.close()


if __name__ == "__main__":
    main()