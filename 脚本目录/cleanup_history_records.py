#!/usr/bin/env python3
"""
清理历史垃圾记录脚本 - 彻底删除已标记为清理的记录
"""

import sqlite3
import shutil
import sys
import os
from datetime import datetime

def backup_database(db_path):
    """备份数据库"""
    backup_path = f"{db_path}.backup_cleanup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup_path)
    print(f"✅ 数据库已备份到: {backup_path}")
    return backup_path

def analyze_cleaned_records(db_path):
    """分析已清理的记录"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 统计已清理记录
        cursor.execute("""
            SELECT 
                COUNT(*) as total_cleaned,
                COUNT(DISTINCT account_id) as affected_accounts
            FROM invites 
            WHERE cleaned = 1
        """)
        total_cleaned, affected_accounts = cursor.fetchone()
        
        # 按账户分组统计
        cursor.execute("""
            SELECT 
                a.email as account_email,
                COUNT(i.id) as cleaned_count
            FROM invites i
            JOIN accounts a ON i.account_id = a.id
            WHERE i.cleaned = 1
            GROUP BY i.account_id, a.email
            ORDER BY cleaned_count DESC
        """)
        account_stats = cursor.fetchall()
        
        # 获取一些示例记录
        cursor.execute("""
            SELECT 
                i.id,
                i.email,
                a.email as account_email,
                i.email_id,
                i.expires_at,
                datetime(i.created_at, 'unixepoch') as created_date
            FROM invites i
            JOIN accounts a ON i.account_id = a.id
            WHERE i.cleaned = 1
            ORDER BY i.created_at DESC
            LIMIT 10
        """)
        sample_records = cursor.fetchall()
        
        return {
            "total_cleaned": total_cleaned,
            "affected_accounts": affected_accounts,
            "account_stats": account_stats,
            "sample_records": sample_records
        }
        
    finally:
        conn.close()

def delete_cleaned_records(db_path, dry_run=True):
    """删除已清理的记录"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        if dry_run:
            # 预览模式，只统计
            cursor.execute("SELECT COUNT(*) FROM invites WHERE cleaned = 1")
            count = cursor.fetchone()[0]
            print(f"[预览] 将删除 {count} 条已清理的记录")
            return count
        else:
            # 实际删除
            cursor.execute("DELETE FROM invites WHERE cleaned = 1")
            deleted_count = cursor.rowcount
            conn.commit()
            print(f"✅ 已删除 {deleted_count} 条历史垃圾记录")
            return deleted_count
            
    except Exception as e:
        conn.rollback()
        print(f"❌ 操作失败: {e}")
        return 0
    finally:
        conn.close()

def main():
    db_path = "/Users/longshu/Desktop/未命名文件夹/newpy_副本/overleaf_inviter.db"
    
    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        return
    
    print("=" * 70)
    print("历史垃圾记录清理工具")
    print("=" * 70)
    
    # 分析当前状态
    print("📊 分析已清理记录...")
    analysis = analyze_cleaned_records(db_path)
    
    print(f"\n📋 统计结果:")
    print(f"  总清理记录: {analysis['total_cleaned']} 条")
    print(f"  涉及账户: {analysis['affected_accounts']} 个")
    
    if analysis['account_stats']:
        print(f"\n🏢 按账户分布:")
        for account_email, count in analysis['account_stats']:
            print(f"  {account_email}: {count} 条")
    
    if analysis['sample_records']:
        print(f"\n📝 示例记录 (最新10条):")
        print("  ID | 邮箱 | 账户 | 创建时间")
        print("  " + "-" * 60)
        for record in analysis['sample_records']:
            record_id, email, account_email, email_id, expires_at, created_date = record
            # 截断长邮箱显示
            short_email = email[:20] + "..." if len(email) > 23 else email
            short_account = account_email.split('@')[0][:10]
            print(f"  {record_id:3d} | {short_email:23s} | {short_account:10s} | {created_date}")
    
    if analysis['total_cleaned'] == 0:
        print("\n✅ 没有需要清理的记录")
        return
    
    # 询问是否继续
    print(f"\n⚠️  准备删除 {analysis['total_cleaned']} 条历史垃圾记录")
    
    if len(sys.argv) > 1 and sys.argv[1] == "--force":
        confirm = "y"
    else:
        confirm = input("是否继续？(y/N): ").lower().strip()
    
    if confirm != 'y':
        print("❌ 操作已取消")
        return
    
    # 备份数据库
    backup_path = backup_database(db_path)
    
    # 预览删除
    print("\n🔍 预览删除操作...")
    delete_cleaned_records(db_path, dry_run=True)
    
    # 实际删除
    print("\n🗑️  执行删除...")
    deleted_count = delete_cleaned_records(db_path, dry_run=False)
    
    if deleted_count > 0:
        print(f"\n🎉 清理完成！")
        print(f"  删除记录: {deleted_count} 条")
        print(f"  备份文件: {backup_path}")
        print(f"\n💡 建议运行: python3 auto_maintenance.py report 验证结果")
    else:
        print(f"\n💥 清理失败，请检查错误信息")

if __name__ == "__main__":
    main()