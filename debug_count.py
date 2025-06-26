#!/usr/bin/env python3
"""
调试计数逻辑
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models

def debug_account_count(email):
    db = SessionLocal()
    try:
        # 找到账户
        account = db.query(models.Account).filter(models.Account.email == email).first()
        if not account:
            print(f"账户 {email} 不存在")
            return
            
        print(f"调试账户: {account.email}")
        print(f"缓存计数: {account.invites_sent}")
        
        # 查看所有邀请记录
        all_invites = db.query(models.Invite).filter(models.Invite.account_id == account.id).all()
        print(f"总邀请记录数: {len(all_invites)}")
        
        # 按邮箱分组统计
        emails = {}
        for invite in all_invites:
            email_addr = invite.email
            if email_addr not in emails:
                emails[email_addr] = []
            emails[email_addr].append({
                'id': invite.id,
                'email_id': invite.email_id,
                'expires_at': invite.expires_at,
                'created_at': invite.created_at,
                'cleaned': invite.cleaned
            })
        
        print(f"唯一邮箱数: {len(emails)}")
        
        # 显示重复邮箱
        duplicates = 0
        for email_addr, invites in emails.items():
            if len(invites) > 1:
                duplicates += 1
                print(f"\n重复邮箱: {email_addr} ({len(invites)} 条记录)")
                for inv in sorted(invites, key=lambda x: x['created_at']):
                    print(f"  ID={inv['id']}, email_id={inv['email_id']}, expires={inv['expires_at']}, cleaned={inv['cleaned']}")
        
        print(f"\n重复邮箱数量: {duplicates}")
        
        # 使用新逻辑计算
        new_count = InviteStatusManager.calculate_invites_sent(db, account)
        print(f"新计数逻辑结果: {new_count}")
        
    finally:
        db.close()

if __name__ == "__main__":
    # 调试一个超额严重的账户
    debug_account_count("ezkcuwl266@hotmail.com")