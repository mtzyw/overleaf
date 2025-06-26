# routers/members_query.py

import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import models, schemas # 引入 models 和 schemas
from database import SessionLocal # 引入 SessionLocal

router = APIRouter(prefix="/api/v1/members_query", tags=["members_query"]) # 修改了 prefix 和 tags

# 定义一个日志器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # 可以根据需要调整日志级别
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/leader_members/{leader_email}", response_model=schemas.LeaderGroupMembersResponse)
def get_leader_group_members(
    leader_email: str,
    db: Session = Depends(get_db)
):
    """
    根据组长邮箱查询其名下所有未过期的组员账号及其过期时间。
    """
    # 1. 查找组长账号
    leader_account = db.query(models.Account).filter(models.Account.email == leader_email).first()
    if not leader_account:
        logger.warning(f"查询组员失败：组长邮箱 '{leader_email}' 不存在。")
        raise HTTPException(status_code=404, detail=f"组长邮箱 '{leader_email}' 不存在。")

    # 2. 获取当前时间戳
    current_timestamp = int(datetime.now().timestamp())

    # 3. 查询该组长的所有邀请记录
    # 这里我们查询所有与该组长关联的邀请记录
    all_invites = (
        db.query(models.Invite)
        .filter(models.Invite.account_id == leader_account.id)
        .all()
    )

    active_members_list = []
    total_members_in_db = 0
    expired_members_count = 0

    for invite in all_invites:
        total_members_in_db += 1
        # 检查是否过期且未清理
        # expires_at=None 表示手动添加的用户，视为活跃用户
        if not invite.cleaned and (invite.expires_at is None or invite.expires_at >= current_timestamp):
            active_members_list.append(schemas.GroupMemberInfo(
                member_email=invite.email,
                expires_at=invite.expires_at,
                email_id=invite.email_id
            ))
        elif invite.expires_at is not None and invite.expires_at < current_timestamp and not invite.cleaned:
            # 统计已过期但未清理的成员（排除手动添加的用户）
            expired_members_count += 1

    logger.info(f"查询组长 '{leader_email}' 的组员信息完成。总成员数: {total_members_in_db}, 活跃成员数: {len(active_members_list)}, 已过期未清理成员数: {expired_members_count}")

    return schemas.LeaderGroupMembersResponse(
        leader_email=leader_email,
        group_id=leader_account.group_id,
        total_members_in_db=total_members_in_db,
        active_members=active_members_list,
        expired_members_count=expired_members_count
    )