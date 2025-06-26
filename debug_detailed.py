#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
import models

def debug_detailed(email):
    db = SessionLocal()
    try:
        account = db.query(models.Account).filter(models.Account.email == email).first()
        if not account:
            print(f"账户 {email} 不存在")
            return
            
        print(f"调试账户: {account.email}")
        print(f"缓存计数: {account.invites_sent}")
        
        # 查看所有邀请记录的详细状态
        all_invites = db.query(models.Invite).filter(models.Invite.account_id == account.id).all()
        print(f"总邀请记录数: {len(all_invites)}")
        
        cleaned_count = 0
        active_count = 0
        
        for invite in all_invites:
            if invite.cleaned:
                cleaned_count += 1
            else:
                active_count += 1
                print(f"活跃记录: ID={invite.id}, email={invite.email}, email_id={invite.email_id}, expires={invite.expires_at}")
        
        print(f"已清理记录数: {cleaned_count}")
        print(f"活跃记录数: {active_count}")
        
    finally:
        db.close()

if __name__ == "__main__":
    debug_detailed("ezkcuwl266@hotmail.com")