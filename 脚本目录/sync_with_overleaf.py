#!/usr/bin/env python3
"""
与Overleaf同步数据库脚本
获取Overleaf的真实成员和邀请数据，修正数据库状态
"""

import sys
import os
import asyncio
import json
import time
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models
from overleaf_utils import get_tokens, get_captcha_token, perform_login, refresh_session, get_new_csrf
import requests


class OverleafSyncer:
    """Overleaf数据同步器"""
    
    def __init__(self):
        self.db = SessionLocal()
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    async def get_group_members(self, account: models.Account):
        """获取Overleaf群组的真实成员数据"""
        session = requests.Session()
        
        # 1. 尝试使用现有token
        if account.session_cookie and account.csrf_token:
            session.cookies.set(
                "overleaf_session2", account.session_cookie,
                domain=".overleaf.com", path="/"
            )
            csrf_token = account.csrf_token
        else:
            # 2. 重新登录获取token
            print(f"账户 {account.email} 需要重新登录...")
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
        
        # 3. 获取群组成员页面
        members_url = f"https://www.overleaf.com/manage/groups/{account.group_id}/members"
        resp = session.get(members_url, headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "max-age=0",
            "priority": "u=0, i",
            "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        })
        
        if resp.status_code != 200:
            raise Exception(f"获取成员数据失败: {resp.status_code} {resp.text}")
        
        # 4. 解析HTML中的ol-users meta标签
        import re
        import html
        html_content = resp.text
        
        # 查找 <meta name="ol-users" data-type="json" content="...">
        meta_pattern = r'<meta\s+name="ol-users"[^>]*content="([^"]*)"'
        match = re.search(meta_pattern, html_content)
        
        if not match:
            raise Exception("未找到ol-users meta标签")
        
        # 解码content内容（可能是HTML实体编码）
        users_content = html.unescape(match.group(1))
        
        # 解析JSON数据
        try:
            users_data = json.loads(users_content)
        except json.JSONDecodeError as e:
            raise Exception(f"解析用户数据失败: {e}")
        
        # 转换为统一格式
        members = []
        for user in users_data:
            # 根据实际数据结构调整字段映射
            members.append({
                "email": user.get("email"),
                "user_id": user.get("_id"),
                "status": "accepted" if user.get("_id") else "pending"
            })
        
        return {
            "members": members,
            "total_count": len(members)
        }
    
    async def sync_account(self, account: models.Account, dry_run=True):
        """同步单个账户的数据"""
        print(f"\n{'='*60}")
        print(f"同步账户: {account.email}")
        print(f"组ID: {account.group_id}")
        print(f"数据库计数: {account.invites_sent}")
        
        try:
            # 1. 获取Overleaf真实数据
            overleaf_data = await self.get_group_members(account)
            overleaf_count = overleaf_data["total_count"]
            overleaf_members = overleaf_data["members"]
            
            print(f"Overleaf实际计数: {overleaf_count}")
            print(f"差值: {account.invites_sent - overleaf_count}")
            
            # 2. 分析数据库中的邀请记录
            db_invites = (
                self.db.query(models.Invite)
                .filter(models.Invite.account_id == account.id)
                .all()
            )
            
            print(f"数据库邀请记录总数: {len(db_invites)}")
            
            # 3. 创建邮箱到Overleaf状态的映射
            overleaf_status = {}
            for member in overleaf_members:
                overleaf_status[member["email"]] = {
                    "user_id": member["user_id"],
                    "status": member["status"]
                }
            
            # 4. 检查数据库外用户（只在Overleaf中存在）
            db_emails = {invite.email for invite in db_invites}
            database_external_users = []
            
            for email, ol_data in overleaf_status.items():
                if email not in db_emails:
                    database_external_users.append({
                        "email": email,
                        "user_id": ol_data["user_id"],
                        "status": ol_data["status"]
                    })
            
            # 5. 分析需要修复的记录
            updates = []
            for invite in db_invites:
                current_status = {
                    "email": invite.email,
                    "db_email_id": invite.email_id,
                    "db_cleaned": invite.cleaned,
                    "overleaf_status": overleaf_status.get(invite.email)
                }
                
                if invite.email in overleaf_status:
                    # 在Overleaf中存在
                    ol_data = overleaf_status[invite.email]
                    
                    if ol_data["status"] == "accepted" and not invite.email_id:
                        # 数据库显示未接受，但Overleaf显示已接受
                        updates.append({
                            "invite_id": invite.id,
                            "action": "update_email_id",
                            "new_email_id": ol_data["user_id"],
                            "reason": "Overleaf显示已接受，但数据库未更新email_id"
                        })
                    
                    if invite.cleaned:
                        # 数据库显示已清理，但Overleaf中还存在
                        updates.append({
                            "invite_id": invite.id,
                            "action": "unmark_cleaned",
                            "reason": "数据库标记为已清理，但Overleaf中仍存在"
                        })
                        
                else:
                    # 在Overleaf中不存在
                    if not invite.cleaned:
                        # 数据库显示未清理，但Overleaf中不存在
                        updates.append({
                            "invite_id": invite.id,
                            "action": "mark_cleaned",
                            "reason": "Overleaf中不存在，应标记为已清理"
                        })
            
            # 6. 显示数据库外用户
            if database_external_users:
                print(f"\n发现数据库外用户: {len(database_external_users)}个")
                for user in database_external_users:
                    print(f"  {user['email']} (user_id: {user['user_id']}, status: {user['status']})")
            
            # 7. 显示需要的修复操作
            print(f"\n需要修复的记录数: {len(updates)}")
            for update in updates:
                print(f"  邀请ID {update['invite_id']}: {update['action']} - {update['reason']}")
            
            # 8. 执行修复（如果不是dry_run）
            if not dry_run:
                if updates:
                    print(f"\n执行修复...")
                    for update in updates:
                        invite = self.db.get(models.Invite, update["invite_id"])
                        if update["action"] == "update_email_id":
                            invite.email_id = update["new_email_id"]
                        elif update["action"] == "unmark_cleaned":
                            invite.cleaned = False
                        elif update["action"] == "mark_cleaned":
                            invite.cleaned = True
                
                # 创建数据库外用户记录
                if database_external_users:
                    print(f"\n创建数据库外用户记录...")
                    import time, json
                    created_count = 0
                    for user in database_external_users:
                        # 创建更完整的result信息
                        result_info = {
                            "source": "manual_sync_from_overleaf",
                            "sync_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "account_manager": account.email,
                            "overleaf_status": user['status'],
                            "overleaf_user_id": user['user_id'],
                            "note": "手动添加的用户，需要联系客户确认过期时间和卡密信息",
                            "action_required": "请设置过期时间并关联正确的卡密",
                            "warning": "设置过期时间后，到期会被正常清理删除"
                        }
                        
                        new_invite = models.Invite(
                            account_id=account.id,
                            card_id=None,  # 手动添加的用户没有卡密，需要后续关联
                            email=user['email'],
                            email_id=user['user_id'] if user['status'] == 'accepted' else None,
                            expires_at=None,  # 关键：不设置过期时间，标记为手动添加
                            success=True,  # 已经在Overleaf中存在
                            result=json.dumps(result_info, ensure_ascii=False),
                            created_at=int(time.time()),
                            cleaned=False
                        )
                        self.db.add(new_invite)
                        created_count += 1
                        print(f"  已创建: {user['email']} (expires_at=NULL, 需要设置过期时间)")
                    
                    print(f"✓ 已创建 {created_count} 个数据库外用户记录")
                
                # 9. 修正账户计数（基于数据库重新计算）
                manager = InviteStatusManager()
                account.invites_sent = manager.calculate_invites_sent(self.db, account)
                self.db.commit()
                print(f"✓ 账户计数已修正: {account.invites_sent}")
            else:
                # dry_run模式，只显示预期结果
                if database_external_users:
                    print(f"\n[DRY-RUN] 将创建 {len(database_external_users)} 个数据库外用户记录")
                print(f"\n[DRY-RUN] 使用 --apply 参数来实际执行修复")
            
            return {
                "account_email": account.email,
                "db_count": account.invites_sent,
                "overleaf_count": overleaf_count,
                "updates_needed": len(updates),
                "success": True
            }
            
        except Exception as e:
            print(f"❌ 同步失败: {str(e)}")
            return {
                "account_email": account.email,
                "error": str(e),
                "success": False
            }
    
    async def sync_all_accounts(self, dry_run=True):
        """同步所有账户"""
        print("="*80)
        print(f"开始同步所有账户 - {'预览模式' if dry_run else '实际执行'}")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        accounts = self.db.query(models.Account).all()
        results = []
        
        for i, account in enumerate(accounts, 1):
            print(f"\n进度: {i}/{len(accounts)}")
            result = await self.sync_account(account, dry_run)
            results.append(result)
            
            # 避免请求过快
            await asyncio.sleep(2)
        
        # 汇总报告
        print("\n" + "="*80)
        print("同步完成汇总:")
        print("="*80)
        
        success_count = len([r for r in results if r["success"]])
        error_count = len([r for r in results if not r["success"]])
        
        print(f"总账户数: {len(accounts)}")
        print(f"成功: {success_count}")
        print(f"失败: {error_count}")
        
        if not dry_run:
            print("\n数据库已更新！建议运行验证脚本确认结果。")
        else:
            print("\n这是预览模式，使用 --apply 参数来实际执行修复。")
        
        return results


async def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python sync_with_overleaf.py <command> [options]")
        print()
        print("命令:")
        print("  sync               - 同步所有账户 (预览模式)")  
        print("  sync --apply       - 同步所有账户 (实际执行)")
        print("  sync-one <email>   - 同步指定账户 (预览模式)")
        print("  sync-one <email> --apply - 同步指定账户 (实际执行)")
        return
    
    command = sys.argv[1]
    dry_run = "--apply" not in sys.argv
    
    syncer = OverleafSyncer()
    
    if command == "sync":
        await syncer.sync_all_accounts(dry_run)
        
    elif command == "sync-one":
        if len(sys.argv) < 3:
            print("请指定账户邮箱")
            return
        
        email = sys.argv[2]
        account = syncer.db.query(models.Account).filter(models.Account.email == email).first()
        if not account:
            print(f"账户 {email} 不存在")
            return
        
        await syncer.sync_account(account, dry_run)
    
    else:
        print(f"未知命令: {command}")


if __name__ == "__main__":
    asyncio.run(main())