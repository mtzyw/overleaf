#!/usr/bin/env python3

import sys, os
sys.path.insert(0, os.getcwd())
from database import SessionLocal
import models
import json, re, html

def check_email_mismatches():
    db = SessionLocal()
    
    print('=== 检查邀请邮箱与接受邮箱不匹配的情况 ===')
    
    # 先从一个已知账户开始检查
    account = db.query(models.Account).filter(models.Account.email == 'ezkcuwl266@hotmail.com').first()
    invites = db.query(models.Invite).filter(
        models.Invite.account_id == account.id,
        models.Invite.email_id.isnot(None),
        models.Invite.cleaned == False
    ).all()
    
    print(f'账户: {account.email}')
    print(f'有email_id的活跃邀请: {len(invites)}条')
    
    # 读取Overleaf用户数据进行对比
    with open('debug_response.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    meta_pattern = r'<meta\s+name="ol-users"[^>]*content="([^"]*)"'
    match = re.search(meta_pattern, content)
    if match:
        users_data = html.unescape(match.group(1))
        users = json.loads(users_data)
        
        # 创建email_id到email的映射
        id_to_email = {user['_id']: user['email'] for user in users}
        
        print('\n=== 邮箱匹配检查 ===')
        mismatches = []
        for invite in invites:
            overleaf_email = id_to_email.get(invite.email_id)
            if overleaf_email and overleaf_email.lower() != invite.email.lower():
                mismatches.append({
                    'invite_id': invite.id,
                    'invited_email': invite.email,
                    'actual_email': overleaf_email,
                    'email_id': invite.email_id
                })
                print(f'❌ 邀请ID {invite.id}: 邀请 {invite.email} → 实际 {overleaf_email}')
            elif overleaf_email:
                print(f'✅ 邀请ID {invite.id}: {invite.email} 匹配')
            else:
                print(f'⚠️  邀请ID {invite.id}: {invite.email} 在Overleaf中未找到对应用户')
        
        print(f'\n发现 {len(mismatches)} 个邮箱不匹配的情况')
        return mismatches

if __name__ == '__main__':
    check_email_mismatches()