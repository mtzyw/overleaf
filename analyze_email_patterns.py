#!/usr/bin/env python3

import sys, os
sys.path.insert(0, os.getcwd())
from database import SessionLocal
import models

def analyze_email_patterns():
    db = SessionLocal()
    
    print('=== 邮箱不匹配问题分析 ===')
    
    # 1. 查找同一个email_id对应多个不同邮箱的情况
    print('\n1. 检查同一个email_id对应多个邮箱:')
    from sqlalchemy import func
    
    # SQLite的group_concat
    duplicates = db.execute("""
        SELECT email_id, 
               COUNT(DISTINCT email) as email_count,
               GROUP_CONCAT(DISTINCT email) as emails
        FROM invites 
        WHERE email_id IS NOT NULL AND cleaned = 0
        GROUP BY email_id 
        HAVING COUNT(DISTINCT email) > 1
    """).fetchall()
    
    if duplicates:
        print(f'  发现 {len(duplicates)} 个email_id对应多个邮箱:')
        for dup in duplicates:
            print(f'    email_id {dup[0]}: {dup[1]}个邮箱 -> {dup[2]}')
    else:
        print('  ✅ 未发现同一email_id对应多个邮箱的情况')
    
    # 2. 查找相同用户名不同域名的情况
    print('\n2. 检查相同用户名不同域名的情况:')
    invites = db.query(models.Invite).filter(
        models.Invite.email_id.isnot(None),
        models.Invite.cleaned == False
    ).all()
    
    # 按用户名分组
    username_groups = {}
    for invite in invites:
        if '@' in invite.email:
            username = invite.email.split('@')[0].lower()
            if username not in username_groups:
                username_groups[username] = []
            username_groups[username].append(invite)
    
    # 找出同一用户名但不同域名且email_id不同的情况
    potential_mismatches = []
    for username, group in username_groups.items():
        if len(group) > 1:
            # 检查是否有不同的email_id
            email_ids = set(inv.email_id for inv in group)
            if len(email_ids) > 1:
                potential_mismatches.append((username, group))
    
    if potential_mismatches:
        print(f'  发现 {len(potential_mismatches)} 个可能的用户名匹配:')
        for username, group in potential_mismatches[:5]:  # 只显示前5个
            print(f'    用户名: {username}')
            for inv in group:
                print(f'      {inv.email} -> email_id: {inv.email_id}')
    else:
        print('  ✅ 未发现明显的用户名匹配问题')
    
    # 3. 查找邀请邮箱为空但有email_id的情况
    print('\n3. 检查异常的email_id情况:')
    
    null_email_invites = db.query(models.Invite).filter(
        models.Invite.email_id.isnot(None),
        models.Invite.email.is_(None),
        models.Invite.cleaned == False
    ).count()
    
    print(f'  邮箱为空但有email_id的记录: {null_email_invites}条')
    
    # 4. 统计概况
    print('\n4. 统计概况:')
    total_active = db.query(models.Invite).filter(models.Invite.cleaned == False).count()
    with_email_id = db.query(models.Invite).filter(
        models.Invite.email_id.isnot(None),
        models.Invite.cleaned == False
    ).count()
    pending = total_active - with_email_id
    
    print(f'  活跃邀请总数: {total_active}')
    print(f'  已接受邀请: {with_email_id}')
    print(f'  待接受邀请: {pending}')
    
    # 5. 检查一些具体的例子来验证
    print('\n5. 随机检查几个有email_id的记录:')
    sample_invites = db.query(models.Invite).filter(
        models.Invite.email_id.isnot(None),
        models.Invite.cleaned == False
    ).limit(10).all()
    
    for inv in sample_invites:
        print(f'  邀请ID {inv.id}: {inv.email} -> email_id: {inv.email_id}')
    
    return potential_mismatches

if __name__ == '__main__':
    analyze_email_patterns()