#!/usr/bin/env python3
"""
手动同步数据库计数
根据用户提供的真实Overleaf数据修正数据库
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
import models


def manual_fix_account(email, real_count, dry_run=True):
    """手动修正账户计数"""
    db = SessionLocal()
    try:
        account = db.query(models.Account).filter(models.Account.email == email).first()
        if not account:
            print(f"❌ 账户 {email} 不存在")
            return False
        
        print(f"账户: {account.email}")
        print(f"数据库计数: {account.invites_sent}")
        print(f"实际计数: {real_count}")
        print(f"差值: {account.invites_sent - real_count}")
        
        if not dry_run:
            account.invites_sent = real_count
            account.updated_at = int(datetime.now().timestamp())
            db.commit()
            print(f"✓ 已修正为: {real_count}")
        else:
            print(f"- 待修正为: {real_count} (dry_run模式)")
        
        return True
        
    finally:
        db.close()


def interactive_sync():
    """交互式同步"""
    print("="*60)
    print("手动数据库同步工具")
    print("="*60)
    
    db = SessionLocal()
    try:
        accounts = db.query(models.Account).all()
        print(f"找到 {len(accounts)} 个账户\n")
        
        for i, account in enumerate(accounts, 1):
            print(f"[{i}/{len(accounts)}] 账户: {account.email}")
            print(f"  组ID: {account.group_id}")
            print(f"  数据库计数: {account.invites_sent}")
            
            while True:
                try:
                    answer = input(f"  请输入Overleaf实际计数 (回车跳过): ").strip()
                    if not answer:
                        print("  ⏭️ 跳过")
                        break
                    
                    real_count = int(answer)
                    if real_count < 0:
                        print("  请输入有效的数字")
                        continue
                    
                    if real_count == account.invites_sent:
                        print("  ✅ 数据一致，无需修正")
                        break
                    
                    # 确认修正
                    confirm = input(f"  确认修正 {account.invites_sent} -> {real_count}? (y/N): ").strip().lower()
                    if confirm == 'y':
                        account.invites_sent = real_count
                        account.updated_at = int(datetime.now().timestamp())
                        db.commit()
                        print(f"  ✓ 已修正为: {real_count}")
                    else:
                        print("  ❌ 取消修正")
                    break
                    
                except ValueError:
                    print("  请输入有效的数字")
                except KeyboardInterrupt:
                    print("\n\n中断操作")
                    return
            
            print()
        
        print("同步完成！")
        
    finally:
        db.close()


def batch_sync_from_file(file_path):
    """从文件批量同步"""
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return
    
    print(f"从文件读取数据: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    updates = []
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        try:
            email, count = line.split(',')
            email = email.strip()
            count = int(count.strip())
            updates.append((email, count))
        except ValueError:
            print(f"第{line_num}行格式错误: {line}")
            continue
    
    print(f"解析到 {len(updates)} 条更新记录")
    
    db = SessionLocal()
    try:
        for email, real_count in updates:
            account = db.query(models.Account).filter(models.Account.email == email).first()
            if not account:
                print(f"❌ 账户不存在: {email}")
                continue
            
            if account.invites_sent != real_count:
                print(f"修正 {email}: {account.invites_sent} -> {real_count}")
                account.invites_sent = real_count
                account.updated_at = int(datetime.now().timestamp())
        
        db.commit()
        print("✓ 批量同步完成")
        
    finally:
        db.close()


def main():
    if len(sys.argv) < 2:
        print("用法: python manual_sync.py <command> [options]")
        print()
        print("命令:")
        print("  interactive        - 交互式逐个修正")
        print("  fix <email> <count> - 修正指定账户")
        print("  batch <file>       - 从文件批量修正")
        print()
        print("批量文件格式 (CSV):")
        print("  email@example.com,22")
        print("  user@test.com,25")
        return
    
    command = sys.argv[1]
    
    if command == "interactive":
        interactive_sync()
        
    elif command == "fix":
        if len(sys.argv) < 4:
            print("用法: python manual_sync.py fix <email> <count>")
            return
        
        email = sys.argv[2]
        try:
            count = int(sys.argv[3])
            manual_fix_account(email, count, dry_run=False)
        except ValueError:
            print("计数必须是数字")
            
    elif command == "batch":
        if len(sys.argv) < 3:
            print("用法: python manual_sync.py batch <file>")
            return
        
        batch_sync_from_file(sys.argv[2])
        
    else:
        print(f"未知命令: {command}")


if __name__ == "__main__":
    main()