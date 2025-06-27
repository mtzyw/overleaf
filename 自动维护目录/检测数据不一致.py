#!/usr/bin/env python3
"""
数据不一致检测脚本
检测所有账户的Overleaf实际用户与数据库记录的差异
只生成报告，不执行删除操作，供手动处理
"""

import sys
import os
import asyncio
import logging
import requests
import json
import re
import html
from datetime import datetime

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models
from overleaf_utils import (
    get_tokens,
    get_captcha_token,
    perform_login,
    refresh_session,
    get_new_csrf
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class DataConsistencyChecker:
    """数据一致性检查器"""
    
    def __init__(self):
        self.db = SessionLocal()
        self.status_manager = InviteStatusManager()
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    async def get_overleaf_members(self, account: models.Account):
        """获取Overleaf群组成员列表"""
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
    
    async def check_account_consistency(self, account: models.Account):
        """检查单个账户的数据一致性"""
        try:
            logger.info(f"🔍 检查账户: {account.email}")
            
            # 1. 获取Overleaf真实数据
            overleaf_members = await self.get_overleaf_members(account)
            overleaf_count = len(overleaf_members)
            overleaf_emails = {member["email"] for member in overleaf_members}
            
            # 2. 获取数据库中的记录
            # 活跃记录（cleaned=False）
            active_invites = (
                self.db.query(models.Invite)
                .filter(models.Invite.account_id == account.id)
                .filter(models.Invite.cleaned == False)
                .all()
            )
            active_count = len(active_invites)
            active_emails = {invite.email for invite in active_invites}
            
            # 所有记录（包括已清理的）
            all_invites = (
                self.db.query(models.Invite)
                .filter(models.Invite.account_id == account.id)
                .all()
            )
            all_emails = {invite.email for invite in all_invites}
            
            # 3. 分析差异
            # 在Overleaf中但不在活跃记录中的用户（这些需要删除）
            need_delete = overleaf_emails - active_emails
            
            # 在Overleaf中但完全不在数据库中的用户（真正的手动用户）
            truly_manual = overleaf_emails - all_emails
            
            # 在活跃记录中但不在Overleaf中的用户（可能是数据库错误）
            db_orphans = active_emails - overleaf_emails
            
            # 被错误标记为cleaned但仍在Overleaf中的用户
            cleaned_invites = (
                self.db.query(models.Invite)
                .filter(models.Invite.account_id == account.id)
                .filter(models.Invite.cleaned == True)
                .all()
            )
            cleaned_emails = {invite.email for invite in cleaned_invites}
            wrongly_cleaned = overleaf_emails & cleaned_emails
            
            logger.info(f"  Overleaf用户数: {overleaf_count}")
            logger.info(f"  数据库活跃记录: {active_count}")
            logger.info(f"  需要删除用户: {len(need_delete)}")
            logger.info(f"  真正手动用户: {len(truly_manual)}")
            logger.info(f"  错误清理标记: {len(wrongly_cleaned)}")
            
            return {
                "account_email": account.email,
                "group_id": account.group_id,
                "overleaf_count": overleaf_count,
                "db_active_count": active_count,
                "overleaf_members": overleaf_members,
                "need_delete": list(need_delete),
                "truly_manual": list(truly_manual),
                "db_orphans": list(db_orphans),
                "wrongly_cleaned": list(wrongly_cleaned),
                "inconsistent": overleaf_count != active_count
            }
            
        except Exception as e:
            logger.error(f"  ❌ 检查失败: {e}")
            return {
                "account_email": account.email,
                "error": str(e),
                "inconsistent": True
            }
    
    async def check_all_accounts(self):
        """检查所有账户的数据一致性"""
        logger.info("🚀 开始检查所有账户的数据一致性...")
        
        accounts = self.db.query(models.Account).all()
        results = []
        
        for i, account in enumerate(accounts, 1):
            logger.info(f"📊 进度: {i}/{len(accounts)}")
            result = await self.check_account_consistency(account)
            results.append(result)
            
            # 避免请求过快
            await asyncio.sleep(2)
        
        return results
    
    def generate_deletion_report(self, results):
        """生成需要删除的用户报告"""
        logger.info("=" * 80)
        logger.info("📋 数据不一致检查报告")
        logger.info("=" * 80)
        
        total_accounts = len(results)
        inconsistent_accounts = len([r for r in results if r.get("inconsistent", False)])
        total_need_delete = sum(len(r.get("need_delete", [])) for r in results)
        total_wrongly_cleaned = sum(len(r.get("wrongly_cleaned", [])) for r in results)
        
        logger.info(f"📊 总账户数: {total_accounts}")
        logger.info(f"📊 数据不一致账户: {inconsistent_accounts}")
        logger.info(f"📊 需要删除的用户总数: {total_need_delete}")
        logger.info(f"📊 错误清理标记用户: {total_wrongly_cleaned}")
        logger.info("")
        
        deletion_list = []
        
        for result in results:
            if result.get("error"):
                logger.error(f"❌ {result['account_email']}: {result['error']}")
                continue
            
            if not result.get("inconsistent", False):
                logger.info(f"✅ {result['account_email']}: 数据一致")
                continue
            
            account_email = result["account_email"]
            group_id = result["group_id"]
            need_delete = result.get("need_delete", [])
            wrongly_cleaned = result.get("wrongly_cleaned", [])
            
            if need_delete or wrongly_cleaned:
                logger.warning(f"⚠️  {account_email} (群组: {group_id}):")
                logger.warning(f"   Overleaf: {result['overleaf_count']} 用户")
                logger.warning(f"   数据库: {result['db_active_count']} 活跃记录")
                
                all_to_delete = list(set(need_delete + wrongly_cleaned))
                logger.warning(f"   需要删除: {len(all_to_delete)} 个用户")
                
                # 获取用户的user_id
                overleaf_members = result.get("overleaf_members", [])
                user_id_map = {member["email"]: member["user_id"] for member in overleaf_members}
                
                for email in all_to_delete:
                    user_id = user_id_map.get(email, "未知")
                    reason = "错误清理标记" if email in wrongly_cleaned else "数据库缺失"
                    logger.warning(f"     - {email} (ID: {user_id}) [{reason}]")
                    
                    deletion_list.append({
                        "account_email": account_email,
                        "group_id": group_id,
                        "user_email": email,
                        "user_id": user_id,
                        "reason": reason,
                        "delete_url": f"https://www.overleaf.com/manage/groups/{group_id}/user/{user_id}"
                    })
                
                logger.warning("")
        
        # 生成详细的删除清单文件
        if deletion_list:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_file = f"需要删除的用户清单_{timestamp}.txt"
            
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("数据不一致用户删除清单\n")
                f.write("=" * 50 + "\n")
                f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"总计需要删除: {len(deletion_list)} 个用户\n\n")
                
                current_account = None
                for item in deletion_list:
                    if current_account != item["account_email"]:
                        current_account = item["account_email"]
                        f.write(f"\n账户: {current_account} (群组ID: {item['group_id']})\n")
                        f.write("-" * 60 + "\n")
                    
                    f.write(f"用户邮箱: {item['user_email']}\n")
                    f.write(f"用户ID: {item['user_id']}\n")
                    f.write(f"删除原因: {item['reason']}\n")
                    f.write(f"删除链接: {item['delete_url']}\n")
                    f.write("\n")
                
                f.write("\n手动删除步骤:\n")
                f.write("1. 登录对应的Overleaf账户\n")
                f.write("2. 访问群组管理页面\n")
                f.write("3. 找到对应用户并删除\n")
                f.write("4. 或者直接访问上面的删除链接\n")
            
            logger.info(f"📄 详细删除清单已保存到: {report_file}")
        
        return deletion_list

async def main():
    """主函数"""
    logger.info("=" * 80)
    logger.info("数据一致性检查任务")
    logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    
    checker = DataConsistencyChecker()
    
    try:
        # 检查所有账户
        results = await checker.check_all_accounts()
        
        # 生成删除报告
        deletion_list = checker.generate_deletion_report(results)
        
        logger.info("🎉 数据一致性检查完成")
        logger.info(f"📋 共发现 {len(deletion_list)} 个用户需要手动删除")
        
        return results
        
    except Exception as e:
        logger.error(f"💥 检查失败: {e}")
        sys.exit(1)
    finally:
        checker.db.close()

if __name__ == "__main__":
    asyncio.run(main())