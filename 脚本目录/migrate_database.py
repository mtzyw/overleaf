#!/usr/bin/env python3
"""
数据库迁移脚本 - 安全地修改expires_at字段支持NULL
"""

import sqlite3
import shutil
import os
from datetime import datetime

def backup_database(db_path):
    """备份数据库"""
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup_path)
    print(f"✅ 数据库已备份到: {backup_path}")
    return backup_path

def migrate_database(db_path):
    """迁移数据库支持expires_at为NULL"""
    print(f"🔄 开始迁移数据库: {db_path}")
    
    # 1. 备份数据库
    backup_path = backup_database(db_path)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 2. 检查当前expires_at字段约束
        cursor.execute("PRAGMA table_info(invites)")
        columns = cursor.fetchall()
        
        expires_at_info = None
        for col in columns:
            if col[1] == 'expires_at':
                expires_at_info = col
                break
        
        if not expires_at_info:
            print("❌ 找不到expires_at字段")
            return False
        
        print(f"📋 当前expires_at字段信息: {expires_at_info}")
        
        # 如果字段已经允许NULL，则不需要迁移
        if expires_at_info[3] == 0:  # nullable = 0 表示允许NULL
            print("✅ expires_at字段已经支持NULL，无需迁移")
            return True
        
        print("🔧 开始迁移...")
        
        # 3. 创建新表结构
        cursor.execute("""
            CREATE TABLE invites_new (
                id INTEGER PRIMARY KEY,
                account_id INTEGER NOT NULL,
                card_id INTEGER,
                email TEXT NOT NULL,
                email_id TEXT,
                expires_at INTEGER,
                success BOOLEAN DEFAULT 0,
                result TEXT,
                created_at INTEGER,
                cleaned BOOLEAN DEFAULT 0,
                FOREIGN KEY (account_id) REFERENCES accounts (id),
                FOREIGN KEY (card_id) REFERENCES cards (id)
            )
        """)
        
        # 4. 复制数据
        cursor.execute("INSERT INTO invites_new SELECT * FROM invites")
        print(f"📋 已复制 {cursor.rowcount} 条记录")
        
        # 5. 删除旧表并重命名新表
        cursor.execute("DROP TABLE invites")
        cursor.execute("ALTER TABLE invites_new RENAME TO invites")
        
        # 6. 验证新结构
        cursor.execute("PRAGMA table_info(invites)")
        new_columns = cursor.fetchall()
        
        new_expires_at_info = None
        for col in new_columns:
            if col[1] == 'expires_at':
                new_expires_at_info = col
                break
        
        if new_expires_at_info and new_expires_at_info[3] == 0:
            print("✅ 迁移成功！expires_at字段现在支持NULL")
            conn.commit()
            return True
        else:
            print("❌ 迁移验证失败")
            conn.rollback()
            return False
            
    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        conn.rollback()
        
        # 恢复备份
        print(f"🔄 正在恢复备份...")
        shutil.copy2(backup_path, db_path)
        print("✅ 数据库已恢复")
        return False
        
    finally:
        conn.close()

def main():
    db_path = "/Users/longshu/Desktop/未命名文件夹/newpy_副本/overleaf_inviter.db"
    
    if not os.path.exists(db_path):
        print(f"❌ 数据库文件不存在: {db_path}")
        return
    
    print("=" * 60)
    print("数据库迁移工具")
    print("=" * 60)
    
    success = migrate_database(db_path)
    
    if success:
        print("\n🎉 迁移完成！现在可以支持手动用户（expires_at=NULL）")
        print("💡 建议运行: python3 auto_maintenance.py report 检查系统状态")
    else:
        print("\n💥 迁移失败，请检查错误信息")
        print("💡 数据库已恢复到迁移前状态")

if __name__ == "__main__":
    main()