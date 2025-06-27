#!/usr/bin/env python3
"""
检测和修复跨群组重复用户问题
"""

import sys
import os
from collections import defaultdict
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
import models

def analyze_duplicate_users():
    """分析跨群组重复用户"""
    db = SessionLocal()
    
    try:
        print("🔍 检测跨群组重复用户...")
        
        # 获取所有未清理的邀请记录
        active_invites = (
            db.query(models.Invite)
            .filter(models.Invite.cleaned.is_(False))
            .all()
        )
        
        # 按邮箱分组
        email_groups = defaultdict(list)
        for invite in active_invites:
            email_groups[invite.email.lower()].append(invite)
        
        # 找出重复用户
        duplicates = {}
        for email, invites in email_groups.items():
            if len(invites) > 1:
                # 按账户分组
                account_groups = defaultdict(list)
                for invite in invites:
                    account_groups[invite.account_id].append(invite)
                
                if len(account_groups) > 1:  # 跨账户重复
                    duplicates[email] = {
                        'total_records': len(invites),
                        'accounts': len(account_groups),
                        'details': account_groups
                    }
        
        if not duplicates:
            print("✅ 没有发现跨群组重复用户")
            return {}
        
        print(f"⚠️  发现 {len(duplicates)} 个跨群组重复用户:")
        
        for email, info in duplicates.items():
            print(f"\n📧 {email}")
            print(f"   总记录数: {info['total_records']}, 涉及账户: {info['accounts']}个")
            
            for account_id, records in info['details'].items():
                account = db.get(models.Account, account_id)
                print(f"   账户: {account.email} ({len(records)}条记录)")
                
                for record in records:
                    created_time = datetime.fromtimestamp(record.created_at).strftime('%Y-%m-%d %H:%M:%S')
                    expires_info = "永不过期" if record.expires_at is None else datetime.fromtimestamp(record.expires_at).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"     - ID:{record.id}, 创建:{created_time}, 过期:{expires_info}, email_id:{record.email_id}")
        
        return duplicates
        
    finally:
        db.close()

def fix_duplicate_users(dry_run=True):
    """修复重复用户（保留最新记录，清理旧记录）"""
    db = SessionLocal()
    
    try:
        duplicates = analyze_duplicate_users()
        if not duplicates:
            return
        
        print(f"\n🔧 {'[DRY-RUN] ' if dry_run else ''}开始修复重复用户...")
        
        fixed_count = 0
        for email, info in duplicates.items():
            print(f"\n处理用户: {email}")
            
            # 收集所有记录并按创建时间排序
            all_records = []
            for account_id, records in info['details'].items():
                all_records.extend(records)
            
            # 按创建时间排序，保留最新的记录
            all_records.sort(key=lambda x: x.created_at, reverse=True)
            keep_record = all_records[0]
            remove_records = all_records[1:]
            
            keep_account = db.get(models.Account, keep_record.account_id)
            print(f"   保留记录: ID:{keep_record.id} 在账户 {keep_account.email}")
            
            for record in remove_records:
                remove_account = db.get(models.Account, record.account_id)
                print(f"   {'[DRY-RUN] ' if dry_run else ''}清理记录: ID:{record.id} 在账户 {remove_account.email}")
                
                if not dry_run:
                    record.cleaned = True
                    record.result = f"自动清理：跨群组重复用户，保留了账户{keep_account.email}中的最新记录"
            
            if not dry_run:
                db.commit()
                fixed_count += 1
        
        if not dry_run:
            print(f"\n✅ 修复完成！处理了 {fixed_count} 个重复用户")
        else:
            print(f"\n💡 DRY-RUN模式完成，使用 --apply 参数来实际执行修复")
        
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="检测和修复跨群组重复用户")
    parser.add_argument("--apply", action="store_true", help="实际执行修复（默认为dry-run模式）")
    parser.add_argument("--analyze-only", action="store_true", help="仅分析，不修复")
    
    args = parser.parse_args()
    
    if args.analyze_only:
        analyze_duplicate_users()
    else:
        fix_duplicate_users(dry_run=not args.apply)