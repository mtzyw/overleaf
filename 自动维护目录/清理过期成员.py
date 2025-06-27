#!/usr/bin/env python3
"""
自动清理过期成员脚本 - 每30分钟执行一次
修复版本：正确调用Overleaf API删除用户，而不只是修改数据库标记
"""

import sys
import os
import time
import asyncio
import logging
import requests
import json
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

# 配置日志 - 只输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class ExpiredMemberCleaner:
    """过期成员清理器"""
    
    def __init__(self):
        self.db = SessionLocal()
        self.manager = InviteStatusManager()
    
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    async def remove_member_from_overleaf(self, invite: models.Invite, account: models.Account):
        """从Overleaf删除已接受的成员"""
        if not invite.email_id:
            raise Exception("无法删除：用户未接受邀请（email_id为空）")
        
        session = requests.Session()
        new_sess = account.session_cookie
        new_csrf = account.csrf_token

        # 尝试复用已有的session/CSRF
        if new_sess and new_csrf:
            session.cookies.set(
                "overleaf_session2", new_sess,
                domain=".overleaf.com", path="/"
            )
            try:
                new_sess = await asyncio.to_thread(refresh_session, session, new_csrf)
                new_csrf = await asyncio.to_thread(get_new_csrf, session, account.group_id)
            except Exception as e:
                logger.warning(f"账号 {account.email} session/CSRF 刷新失败: {e}. 将尝试完整登录。")
                new_sess = new_csrf = None

        # 如复用失败，完整登录流程
        if not (new_sess and new_csrf):
            csrf0, sess0 = await get_tokens()
            captcha = get_captcha_token()
            session = await asyncio.to_thread(
                perform_login, csrf0, sess0,
                account.email, account.password, captcha
            )
            new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, account.group_id)

        # 更新数据库中的token
        account.session_cookie = new_sess
        account.csrf_token = new_csrf
        self.db.commit()

        # 调用Overleaf API删除组员
        url = f"https://www.overleaf.com/manage/groups/{account.group_id}/user/{invite.email_id}"
        
        logger.info(f"尝试从Overleaf删除成员: {invite.email} (email_id: {invite.email_id})")

        resp = session.delete(url, headers={
            "Accept": "application/json",
            "x-csrf-token": new_csrf,
            "Referer": f"https://www.overleaf.com/manage/groups/{account.group_id}/members",
            "User-Agent": "Mozilla/5.0"
        })

        # 处理不同的响应状态
        if resp.status_code in (200, 204):
            logger.info(f"✅ 成功从Overleaf删除成员: {invite.email}")
            return {"success": True, "message": "删除成功"}
        elif resp.status_code == 404:
            logger.warning(f"⚠️ 成员已不存在: {invite.email}，将标记为已处理")
            return {"success": True, "message": "成员已不存在"}
        else:
            # 其他错误
            try:
                error_data = resp.json()
                error_detail = error_data.get('error', {}).get('message', resp.text)
            except json.JSONDecodeError:
                error_detail = resp.text
            raise Exception(f"Overleaf API错误 {resp.status_code}: {error_detail}")

    async def revoke_pending_invite(self, invite: models.Invite, account: models.Account):
        """撤销未接受的邀请"""
        session = requests.Session()
        new_sess = account.session_cookie
        new_csrf = account.csrf_token

        # 尝试复用已有的session/CSRF (同上)
        if new_sess and new_csrf:
            session.cookies.set(
                "overleaf_session2", new_sess,
                domain=".overleaf.com", path="/"
            )
            try:
                new_sess = await asyncio.to_thread(refresh_session, session, new_csrf)
                new_csrf = await asyncio.to_thread(get_new_csrf, session, account.group_id)
            except Exception as e:
                logger.warning(f"账号 {account.email} session/CSRF 刷新失败: {e}. 将尝试完整登录。")
                new_sess = new_csrf = None

        if not (new_sess and new_csrf):
            csrf0, sess0 = await get_tokens()
            captcha = get_captcha_token()
            session = await asyncio.to_thread(
                perform_login, csrf0, sess0,
                account.email, account.password, captcha
            )
            new_sess = await asyncio.to_thread(refresh_session, session, csrf0)
            new_csrf = await asyncio.to_thread(get_new_csrf, session, account.group_id)

        # 更新数据库中的token
        account.session_cookie = new_sess
        account.csrf_token = new_csrf
        self.db.commit()

        # 调用Overleaf API撤销邀请
        encoded_email = requests.utils.quote(invite.email, safe='')
        url = f"https://www.overleaf.com/manage/groups/{account.group_id}/invites/{encoded_email}"

        logger.info(f"尝试撤销Overleaf邀请: {invite.email}")

        resp = session.delete(url, headers={
            "Accept": "application/json",
            "x-csrf-token": new_csrf,
            "Referer": f"https://www.overleaf.com/manage/groups/{account.group_id}/members",
            "User-Agent": "Mozilla/5.0"
        })

        if resp.status_code in (200, 204):
            logger.info(f"✅ 成功撤销Overleaf邀请: {invite.email}")
            return {"success": True, "message": "撤销成功"}
        elif resp.status_code == 404:
            logger.warning(f"⚠️ 邀请已不存在: {invite.email}，将标记为已处理")
            return {"success": True, "message": "邀请已不存在"}
        else:
            try:
                error_data = resp.json()
                error_detail = error_data.get('error', {}).get('message', resp.text)
            except json.JSONDecodeError:
                error_detail = resp.text
            raise Exception(f"Overleaf API错误 {resp.status_code}: {error_detail}")

    async def cleanup_expired_members(self):
        """清理过期成员 - 修复版本"""
        try:
            logger.info("🗑️ 开始清理过期成员...")
            
            now_ts = int(time.time())
            
            # 查找过期的邀请（排除手动用户）
            expired_invites = (
                self.db.query(models.Invite)
                .filter(models.Invite.expires_at.isnot(None))  # 排除手动用户
                .filter(models.Invite.expires_at < now_ts)
                .filter(models.Invite.cleaned == False)
                .limit(50)  # 限制批次大小，避免超时
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
                    "expired_days": (now_ts - invite.expires_at) // 86400,
                    "has_email_id": bool(invite.email_id)
                })
            
            # 执行清理
            success_count = 0
            error_count = 0
            affected_accounts = set()
            
            for invite in expired_invites:
                try:
                    account = self.db.get(models.Account, invite.account_id)
                    if not account:
                        logger.error(f"❌ 找不到账户信息: invite_id={invite.id}")
                        error_count += 1
                        continue
                    
                    status = self.manager.get_invite_status(invite)
                    
                    if status == InviteStatusManager.InviteStatus.ACCEPTED:
                        # 已接受的邀请，需要调用删除成员API
                        result = await self.remove_member_from_overleaf(invite, account)
                        if result["success"]:
                            # 真正删除数据库记录
                            self.db.delete(invite)
                            success_count += 1
                            affected_accounts.add(invite.account_id)
                            logger.info(f"✅ 已删除过期成员: {invite.email}")
                        else:
                            error_count += 1
                            
                    elif status == InviteStatusManager.InviteStatus.PENDING:
                        # 未接受的邀请，撤销邀请
                        result = await self.revoke_pending_invite(invite, account)
                        if result["success"]:
                            # 真正删除数据库记录
                            self.db.delete(invite)
                            success_count += 1
                            affected_accounts.add(invite.account_id)
                            logger.info(f"✅ 已撤销过期邀请: {invite.email}")
                        else:
                            error_count += 1
                            
                    else:
                        # 其他状态，直接标记为已处理
                        invite.cleaned = True
                        success_count += 1
                        affected_accounts.add(invite.account_id)
                        logger.info(f"✅ 标记过期邀请为已处理: {invite.email}")
                    
                    # 避免请求过快
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"❌ 清理失败 {invite.email}: {e}")
                    error_count += 1
                    # 发生错误时，标记为已处理避免重复尝试
                    invite.cleaned = True
                    affected_accounts.add(invite.account_id)
            
            # 更新受影响账户的计数
            for account_id in affected_accounts:
                account = self.db.get(models.Account, account_id)
                if account:
                    account.invites_sent = self.manager.calculate_invites_sent(self.db, account)
            
            self.db.commit()
            
            processed_count = success_count + error_count
            logger.info(f"✅ 清理完成: 成功 {success_count} 个，失败 {error_count} 个，影响 {len(affected_accounts)} 个账户")
            
            # 详细统计
            for account_email, members in by_account.items():
                logger.info(f"  {account_email}: {len(members)} 个过期成员")
            
            return {
                "success": True,
                "expired_count": len(expired_invites),
                "processed_count": processed_count,
                "success_count": success_count,
                "error_count": error_count,
                "affected_accounts": len(affected_accounts),
                "details": by_account
            }
            
        except Exception as e:
            logger.error(f"❌ 清理失败: {e}")
            self.db.rollback()
            return {
                "success": False,
                "error": str(e)
            }

async def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("自动清理过期成员任务 - 修复版本")
    logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)
    
    cleaner = ExpiredMemberCleaner()
    
    try:
        result = await cleaner.cleanup_expired_members()
        
        if result["success"]:
            if "success_count" in result:
                logger.info(f"🎉 清理完成: 成功 {result['success_count']} 个，失败 {result.get('error_count', 0)} 个")
            else:
                logger.info(f"🎉 清理完成: 处理了 {result['processed_count']} 个过期成员")
        else:
            logger.error(f"💥 清理失败: {result['error']}")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"💥 清理异常: {e}")
        sys.exit(1)
    finally:
        cleaner.db.close()

if __name__ == "__main__":
    asyncio.run(main())