#!/usr/bin/env python3
"""
数据一致性修复脚本
用于修复账户邀请计数不准确和其他数据一致性问题
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models


def print_header(title):
    """打印格式化的标题"""
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)


def print_summary(title, items):
    """打印摘要信息"""
    print(f"\n{title}:")
    if not items:
        print("  无问题发现")
    else:
        for i, item in enumerate(items, 1):
            print(f"  {i}. {item}")


def validate_data():
    """验证数据一致性"""
    print_header("数据一致性验证")
    
    db = SessionLocal()
    try:
        issues = InviteStatusManager.validate_data_consistency(db)
        
        count_issues = [i for i in issues if i["type"] == "count_mismatch"]
        logic_issues = [i for i in issues if i["type"] != "count_mismatch"]
        
        print(f"发现 {len(issues)} 个数据一致性问题:")
        print(f"  - 计数不匹配: {len(count_issues)} 个")
        print(f"  - 逻辑不一致: {len(logic_issues)} 个")
        
        if count_issues:
            print("\n计数不匹配详情:")
            for issue in count_issues:
                print(f"  账户: {issue['account_email']}")
                print(f"    缓存计数: {issue['cached_count']}")
                print(f"    实际计数: {issue['real_count']}")
                print(f"    差值: {issue['difference']}")
                print()
        
        if logic_issues:
            print("\n逻辑不一致详情:")
            for issue in logic_issues:
                print(f"  类型: {issue['type']}")
                print(f"  邀请ID: {issue.get('invite_id', 'N/A')}")
                print(f"  邮箱: {issue.get('email', 'N/A')}")
                print(f"  描述: {issue.get('description', 'N/A')}")
                print()
        
        return issues
        
    finally:
        db.close()


def fix_account_counts(dry_run=True):
    """修复账户邀请计数"""
    print_header("修复账户邀请计数")
    
    db = SessionLocal()
    try:
        accounts = db.query(models.Account).all()
        fixed_count = 0
        
        for account in accounts:
            real_count = InviteStatusManager.calculate_invites_sent(db, account)
            if account.invites_sent != real_count:
                print(f"账户 {account.email}:")
                print(f"  当前计数: {account.invites_sent}")
                print(f"  实际计数: {real_count}")
                print(f"  差值: {account.invites_sent - real_count}")
                
                if not dry_run:
                    InviteStatusManager.sync_account_invites_count(db, account)
                    print(f"  ✓ 已修复")
                else:
                    print(f"  - 待修复 (dry_run模式)")
                
                fixed_count += 1
                print()
        
        if fixed_count == 0:
            print("所有账户计数都是准确的！")
        else:
            action = "将被修复" if dry_run else "已修复"
            print(f"总计 {fixed_count} 个账户的计数{action}")
            
        return fixed_count
        
    finally:
        db.close()


def generate_status_report():
    """生成详细的状态报告"""
    print_header("系统状态报告")
    
    db = SessionLocal()
    try:
        accounts = db.query(models.Account).all()
        
        print(f"账户总数: {len(accounts)}")
        print()
        
        total_invites = 0
        total_quota = 0
        status_stats = {
            "pending": 0,
            "accepted": 0, 
            "expired": 0,
            "processed": 0
        }
        
        for account in accounts:
            summary = InviteStatusManager.get_account_status_summary(db, account)
            
            print(f"账户: {account.email}")
            print(f"  组ID: {account.group_id}")
            print(f"  邀请计数: {summary['invites_sent_cached']} (缓存) / {summary['invites_sent_real']} (实际)")
            print(f"  可用配额: {summary['available_quota']} / {summary['max_invites']}")
            print(f"  状态分布: {summary['status_breakdown']}")
            print(f"  数据一致: {'❌' if summary['count_mismatch'] else '✅'}")
            print()
            
            total_invites += summary['invites_sent_real']
            total_quota += summary['max_invites']
            
            for status, count in summary['status_breakdown'].items():
                status_stats[status] += count
        
        print("="*40)
        print("全局统计:")
        print(f"  总活跃邀请: {total_invites}")
        print(f"  总配额: {total_quota}")
        print(f"  配额利用率: {total_invites/total_quota*100:.1f}%")
        print(f"  状态分布: {status_stats}")
        
    finally:
        db.close()


def add_validation_api():
    """添加数据验证API接口"""
    print_header("添加数据验证API")
    
    api_code = '''
# 在 routers/remove_member.py 中添加以下接口

@router.get("/status/validation")
async def validate_system_status(db: Session = Depends(get_db)):
    """验证系统数据一致性"""
    issues = InviteStatusManager.validate_data_consistency(db)
    return {
        "total_issues": len(issues),
        "issues": issues,
        "checked_at": int(time.time())
    }

@router.get("/status/account/{account_email}")
async def get_account_status(account_email: str, db: Session = Depends(get_db)):
    """获取指定账户的详细状态"""
    account = db.query(models.Account).filter(models.Account.email == account_email).first()
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")
    return InviteStatusManager.get_account_status_summary(db, account)

@router.post("/fix/account_counts")
async def fix_account_counts(db: Session = Depends(get_db)):
    """修复所有账户的邀请计数"""
    accounts = db.query(models.Account).all()
    fixed_count = 0
    
    for account in accounts:
        if InviteStatusManager.sync_account_invites_count(db, account):
            fixed_count += 1
    
    return {
        "fixed_accounts": fixed_count,
        "total_accounts": len(accounts),
        "fixed_at": int(time.time())
    }
'''
    
    print("建议在API中添加以下接口用于监控和修复:")
    print(api_code)


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python fix_data_consistency.py <command> [options]")
        print()
        print("命令:")
        print("  validate           - 验证数据一致性")
        print("  fix-counts         - 修复账户计数 (dry-run)")
        print("  fix-counts --apply - 修复账户计数 (实际执行)")
        print("  report             - 生成状态报告")
        print("  add-api            - 显示建议添加的API接口")
        return
    
    command = sys.argv[1]
    
    print(f"数据一致性修复脚本 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if command == "validate":
        issues = validate_data()
        sys.exit(1 if issues else 0)
        
    elif command == "fix-counts":
        dry_run = "--apply" not in sys.argv
        if dry_run:
            print("注意: 运行在 dry-run 模式，不会实际修改数据")
            print("使用 --apply 参数来实际执行修复")
        
        fixed_count = fix_account_counts(dry_run)
        sys.exit(0 if fixed_count == 0 else 1)
        
    elif command == "report":
        generate_status_report()
        
    elif command == "add-api":
        add_validation_api()
        
    else:
        print(f"未知命令: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()