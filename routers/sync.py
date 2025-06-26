#!/usr/bin/env python3
"""
同步API路由 - 将同步脚本功能封装为API接口
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models
from overleaf_utils import get_tokens, get_captcha_token, perform_login, refresh_session, get_new_csrf
import requests
import json
import re
import html

# 创建路由器
router = APIRouter(prefix="/api/v1/sync", tags=["同步管理"])

# 依赖项：获取数据库会话
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 响应模型
class SyncResult(BaseModel):
    """单个账户同步结果"""
    account_email: str
    account_id: int
    group_id: str
    db_count: int
    overleaf_count: int
    difference: int
    database_external_users: List[Dict]
    updates_applied: List[Dict]
    success: bool
    error_message: Optional[str] = None
    sync_time: str

class BatchSyncResult(BaseModel):
    """批量同步结果"""
    total_accounts: int
    success_count: int
    failed_count: int
    total_external_users_created: int
    total_updates_applied: int
    results: List[SyncResult]
    start_time: str
    end_time: str
    duration_seconds: float

class SyncStatus(BaseModel):
    """同步状态"""
    is_running: bool
    current_account: Optional[str] = None
    progress: str
    start_time: Optional[str] = None
    estimated_remaining: Optional[str] = None

# 全局状态管理
class SyncManager:
    def __init__(self):
        self.is_running = False
        self.current_account = None
        self.start_time = None
        self.total_accounts = 0
        self.completed_accounts = 0

sync_manager = SyncManager()

class OverleafSyncer:
    """Overleaf数据同步器"""
    
    def __init__(self, db: Session):
        self.db = db
        
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
    
    async def sync_account(self, account: models.Account) -> SyncResult:
        """同步单个账户的数据"""
        sync_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            # 1. 获取Overleaf真实数据
            overleaf_data = await self.get_group_members(account)
            overleaf_count = overleaf_data["total_count"]
            overleaf_members = overleaf_data["members"]
            
            # 2. 分析数据库中的邀请记录
            db_invites = (
                self.db.query(models.Invite)
                .filter(models.Invite.account_id == account.id)
                .all()
            )
            
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
            
            # 6. 执行修复
            updates_applied = []
            
            # 修复现有记录
            for update in updates:
                invite = self.db.get(models.Invite, update["invite_id"])
                if update["action"] == "update_email_id":
                    invite.email_id = update["new_email_id"]
                elif update["action"] == "unmark_cleaned":
                    invite.cleaned = False
                elif update["action"] == "mark_cleaned":
                    invite.cleaned = True
                updates_applied.append(update)
            
            # 创建数据库外用户记录
            external_users_created = []
            if database_external_users:
                for user in database_external_users:
                    # 创建更完整的result信息
                    result_info = {
                        "source": "manual_sync_from_overleaf",
                        "sync_date": sync_time,
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
                    external_users_created.append(user)
            
            # 7. 修正账户计数（基于数据库重新计算）
            manager = InviteStatusManager()
            account.invites_sent = manager.calculate_invites_sent(self.db, account)
            self.db.commit()
            
            return SyncResult(
                account_email=account.email,
                account_id=account.id,
                group_id=account.group_id,
                db_count=account.invites_sent,
                overleaf_count=overleaf_count,
                difference=account.invites_sent - overleaf_count,
                database_external_users=external_users_created,
                updates_applied=updates_applied,
                success=True,
                sync_time=sync_time
            )
            
        except Exception as e:
            return SyncResult(
                account_email=account.email,
                account_id=account.id,
                group_id=account.group_id,
                db_count=account.invites_sent,
                overleaf_count=0,
                difference=0,
                database_external_users=[],
                updates_applied=[],
                success=False,
                error_message=str(e),
                sync_time=sync_time
            )

@router.get("/status", response_model=SyncStatus)
async def get_sync_status():
    """获取当前同步状态"""
    estimated_remaining = None
    if sync_manager.is_running and sync_manager.total_accounts > 0:
        progress_pct = sync_manager.completed_accounts / sync_manager.total_accounts
        if progress_pct > 0 and sync_manager.start_time:
            elapsed = time.time() - sync_manager.start_time
            total_estimated = elapsed / progress_pct
            estimated_remaining = f"{int((total_estimated - elapsed) / 60)}分钟"
    
    return SyncStatus(
        is_running=sync_manager.is_running,
        current_account=sync_manager.current_account,
        progress=f"{sync_manager.completed_accounts}/{sync_manager.total_accounts}" if sync_manager.total_accounts > 0 else "0/0",
        start_time=datetime.fromtimestamp(sync_manager.start_time).strftime('%Y-%m-%d %H:%M:%S') if sync_manager.start_time else None,
        estimated_remaining=estimated_remaining
    )

@router.post("/all", response_model=Dict[str, str])
async def start_sync_all_accounts(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """启动所有账户的同步任务（后台异步执行）"""
    if sync_manager.is_running:
        raise HTTPException(status_code=400, detail="同步任务正在进行中，请等待完成")
    
    accounts = db.query(models.Account).all()
    sync_manager.total_accounts = len(accounts)
    sync_manager.completed_accounts = 0
    sync_manager.is_running = True
    sync_manager.start_time = time.time()
    
    # 添加后台任务
    background_tasks.add_task(run_batch_sync, accounts)
    
    return {
        "message": f"已启动 {len(accounts)} 个账户的同步任务",
        "status": "running",
        "total_accounts": len(accounts)
    }

@router.post("/account/{email}", response_model=SyncResult)
async def sync_single_account(
    email: str,
    db: Session = Depends(get_db)
):
    """同步指定账户"""
    account = db.query(models.Account).filter(models.Account.email == email).first()
    if not account:
        raise HTTPException(status_code=404, detail=f"账户 {email} 不存在")
    
    syncer = OverleafSyncer(db)
    result = await syncer.sync_account(account)
    
    return result

async def run_batch_sync(accounts: List[models.Account]):
    """后台执行批量同步"""
    db = SessionLocal()
    try:
        syncer = OverleafSyncer(db)
        results = []
        
        for i, account in enumerate(accounts, 1):
            sync_manager.current_account = account.email
            sync_manager.completed_accounts = i - 1
            
            result = await syncer.sync_account(account)
            results.append(result)
            
            # 避免请求过快
            await asyncio.sleep(2)
        
        sync_manager.completed_accounts = len(accounts)
        
    except Exception as e:
        print(f"批量同步错误: {e}")
    finally:
        sync_manager.is_running = False
        sync_manager.current_account = None
        db.close()

@router.get("/results", response_model=Dict[str, str])
async def get_last_sync_results():
    """获取最后一次同步的结果摘要"""
    if sync_manager.is_running:
        return {
            "status": "running",
            "message": "同步正在进行中"
        }
    else:
        return {
            "status": "completed",
            "message": f"上次同步已完成，共处理 {sync_manager.total_accounts} 个账户"
        }