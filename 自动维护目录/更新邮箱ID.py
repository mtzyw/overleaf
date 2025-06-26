#!/usr/bin/env python3
"""
自动更新邮箱ID脚本 - 每1小时执行一次
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

class EmailIdUpdater:
    """邮箱ID更新器"""
    
    def __init__(self):
        self.db = SessionLocal()
        
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
    
    async def update_account_email_ids(self, account: models.Account):
        """更新单个账户的email_id"""
        try:
            logger.info(f"📧 处理账户: {account.email}")
            
            # 获取Overleaf群组成员数据
            overleaf_members = await self.get_overleaf_members(account)
            
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
                .filter(models.Invite.cleaned == False)   # 只更新活跃记录
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
                logger.info(f"  ✅ 更新了 {updated_count} 个email_id")
                for email in updated_emails:
                    logger.info(f"    - {email}")
            else:
                logger.info(f"  ✅ 无需更新")
            
            return {
                "account_email": account.email,
                "success": True,
                "updated_count": updated_count,
                "updated_emails": updated_emails,
                "overleaf_total_members": len(overleaf_members)
            }
            
        except Exception as e:
            logger.error(f"  ❌ 更新失败: {e}")
            return {
                "account_email": account.email,
                "success": False,
                "error": str(e),
                "updated_count": 0
            }
    
    async def update_all_email_ids(self):
        """更新所有账户的email_id"""
        logger.info("📧 开始更新所有账户的email_id...")
        
        accounts = self.db.query(models.Account).all()
        results = {
            "total_accounts": len(accounts),
            "success_accounts": 0,
            "failed_accounts": 0,
            "total_updated": 0,
            "account_results": []
        }
        
        for i, account in enumerate(accounts, 1):
            logger.info(f"📊 进度: {i}/{len(accounts)}")
            
            try:
                account_result = await self.update_account_email_ids(account)
                results["account_results"].append(account_result)
                
                if account_result["success"]:
                    results["success_accounts"] += 1
                    results["total_updated"] += account_result["updated_count"]
                else:
                    results["failed_accounts"] += 1
                    
                # 避免请求过快
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"❌ 处理账户 {account.email} 时发生错误: {e}")
                results["failed_accounts"] += 1
                results["account_results"].append({
                    "account_email": account.email,
                    "success": False,
                    "error": str(e),
                    "updated_count": 0
                })
        
        logger.info(f"📧 email_id更新完成: 成功{results['success_accounts']}个，失败{results['failed_accounts']}个，总共更新{results['total_updated']}条记录")
        return results

async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("自动更新邮箱ID任务")
    logger.info("=" * 60)
    
    updater = EmailIdUpdater()
    
    try:
        result = await updater.update_all_email_ids()
        
        if result["total_updated"] > 0:
            logger.info(f"🎉 更新完成: 共更新 {result['total_updated']} 个邮箱ID")
        else:
            logger.info("✅ 所有邮箱ID都是最新的，无需更新")
        
        return result
        
    except Exception as e:
        logger.error(f"💥 更新失败: {e}")
        sys.exit(1)
    finally:
        updater.db.close()

if __name__ == "__main__":
    asyncio.run(main())