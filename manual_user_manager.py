#!/usr/bin/env python3
"""
手动用户管理工具
用于管理expires_at=NULL的手动添加用户
"""

import sys, os
sys.path.insert(0, os.getcwd())
from database import SessionLocal
import models
import json
import time

def list_manual_users():
    """列出所有手动添加的用户"""
    db = SessionLocal()
    
    manual_users = db.query(models.Invite).filter(
        models.Invite.expires_at.is_(None),
        models.Invite.cleaned == False
    ).all()
    
    print(f'=== 手动添加的用户列表 ({len(manual_users)}个) ===')
    
    for invite in manual_users:
        account = db.query(models.Account).filter(models.Account.id == invite.account_id).first()
        
        print(f'\n邀请ID: {invite.id}')
        print(f'邮箱: {invite.email}')
        print(f'组长账户: {account.email if account else "未知"}')
        print(f'email_id: {invite.email_id}')
        print(f'过期时间: {invite.expires_at} (NULL = 手动添加)')
        print(f'卡密ID: {invite.card_id}')
        
        # 解析result信息
        try:
            result_data = json.loads(invite.result)
            if isinstance(result_data, dict):
                print(f'来源: {result_data.get("source", "未知")}')
                print(f'同步时间: {result_data.get("sync_date", "未知")}')
                print(f'状态: {result_data.get("overleaf_status", "未知")}')
                if "warning" in result_data:
                    print(f'⚠️ 警告: {result_data["warning"]}')
        except:
            print(f'原始信息: {invite.result}')
    
    db.close()
    return manual_users

def set_expiry_for_manual_user(invite_id: int, days: int, card_code: str = None):
    """为手动用户设置过期时间和卡密"""
    db = SessionLocal()
    
    invite = db.query(models.Invite).filter(models.Invite.id == invite_id).first()
    if not invite:
        print(f'❌ 邀请ID {invite_id} 不存在')
        return False
    
    if invite.expires_at is not None:
        print(f'❌ 邀请ID {invite_id} 已经有过期时间: {invite.expires_at}')
        return False
    
    # 设置过期时间
    expires_at = int(time.time()) + (days * 24 * 3600)
    invite.expires_at = expires_at
    
    # 关联卡密（如果提供）
    if card_code:
        card = db.query(models.Card).filter(models.Card.code == card_code).first()
        if card:
            invite.card_id = card.id
            print(f'✅ 已关联卡密: {card_code}')
        else:
            print(f'⚠️ 卡密 {card_code} 不存在，但已设置过期时间')
    
    # 更新result信息
    try:
        result_data = json.loads(invite.result)
        if isinstance(result_data, dict):
            result_data.update({
                "expires_set_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                "expires_days": days,
                "card_code": card_code,
                "status": "已设置过期时间，现在会被正常管理"
            })
            invite.result = json.dumps(result_data, ensure_ascii=False)
    except:
        # 如果原result不是JSON，创建新的
        result_data = {
            "original_info": invite.result,
            "expires_set_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "expires_days": days,
            "card_code": card_code,
            "status": "已设置过期时间，现在会被正常管理"
        }
        invite.result = json.dumps(result_data, ensure_ascii=False)
    
    db.commit()
    
    print(f'✅ 已为用户 {invite.email} 设置过期时间: {days}天')
    print(f'   过期时间戳: {expires_at}')
    print(f'   过期日期: {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at))}')
    
    db.close()
    return True

def create_warning_report():
    """创建手动用户警告报告"""
    db = SessionLocal()
    
    manual_users = db.query(models.Invite).filter(
        models.Invite.expires_at.is_(None),
        models.Invite.cleaned == False
    ).all()
    
    print(f'=== 手动用户警告报告 ===')
    print(f'发现 {len(manual_users)} 个需要处理的手动添加用户\n')
    
    account_groups = {}
    for invite in manual_users:
        account = db.query(models.Account).filter(models.Account.id == invite.account_id).first()
        account_email = account.email if account else "未知账户"
        
        if account_email not in account_groups:
            account_groups[account_email] = []
        account_groups[account_email].append(invite)
    
    for account_email, invites in account_groups.items():
        print(f'组长账户: {account_email}')
        for invite in invites:
            print(f'  - {invite.email} (ID: {invite.id})')
        print(f'  需要处理: {len(invites)}个用户\n')
    
    print('⚠️ 警告事项:')
    print('1. 这些用户当前不会过期，占用群组配额')
    print('2. 需要联系客户确认过期时间')
    print('3. 设置过期时间后，到期会被正常清理')
    print('4. 建议关联正确的卡密以便追踪')
    
    db.close()

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='手动用户管理工具')
    parser.add_argument('action', choices=['list', 'set-expiry', 'report'], 
                       help='操作类型')
    parser.add_argument('--invite-id', type=int, help='邀请ID')
    parser.add_argument('--days', type=int, help='过期天数')
    parser.add_argument('--card-code', help='卡密代码')
    
    args = parser.parse_args()
    
    if args.action == 'list':
        list_manual_users()
    elif args.action == 'report':
        create_warning_report()
    elif args.action == 'set-expiry':
        if not args.invite_id or not args.days:
            print('❌ set-expiry 需要 --invite-id 和 --days 参数')
            return
        set_expiry_for_manual_user(args.invite_id, args.days, args.card_code)

if __name__ == '__main__':
    main()