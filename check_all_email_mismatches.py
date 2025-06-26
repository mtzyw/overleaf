#!/usr/bin/env python3

import sys, os
sys.path.insert(0, os.getcwd())
from database import SessionLocal
import models

def check_all_email_mismatches():
    db = SessionLocal()
    
    print('=== 全局邮箱不匹配检查 ===\n')
    
    # 查找所有有email_id但可能不匹配的邀请
    total_mismatches = 0
    
    # 获取所有账户
    accounts = db.query(models.Account).all()
    
    for account in accounts:
        # 查找该账户的所有有email_id的活跃邀请
        invites = db.query(models.Invite).filter(
            models.Invite.account_id == account.id,
            models.Invite.email_id.isnot(None),
            models.Invite.cleaned == False
        ).all()
        
        if len(invites) == 0:
            continue
            
        print(f'账户: {account.email}')
        print(f'有email_id的活跃邀请: {len(invites)}条')
        
        # 通过API获取这个账户的Overleaf用户数据
        try:
            # 这里我们可以复用sync脚本的逻辑
            from 脚本目录.sync_with_overleaf import OverleafSyncer
            syncer = OverleafSyncer()
            overleaf_users = syncer.get_overleaf_members(account)
            
            # 创建email_id到email的映射
            id_to_email = {user['_id']: user['email'] for user in overleaf_users}
            
            account_mismatches = 0
            for invite in invites:
                overleaf_email = id_to_email.get(invite.email_id)
                if overleaf_email and overleaf_email.lower() != invite.email.lower():
                    account_mismatches += 1
                    total_mismatches += 1
                    print(f'  ❌ 邀请ID {invite.id}: {invite.email} → {overleaf_email}')
            
            if account_mismatches == 0:
                print(f'  ✅ 所有邮箱匹配正确')
            else:
                print(f'  ⚠️  发现 {account_mismatches} 个不匹配')
                
        except Exception as e:
            print(f'  ❌ 无法获取Overleaf数据: {e}')
        
        print()
    
    print(f'=== 总计发现 {total_mismatches} 个邮箱不匹配问题 ===')

if __name__ == '__main__':
    check_all_email_mismatches()