#!/usr/bin/env python3

import sys, os
sys.path.insert(0, os.getcwd())
from database import SessionLocal
from invite_status_manager import InviteStatusManager
import models

def analyze_final_status():
    db = SessionLocal()
    
    print('=== 最终数据状态检查和异常账户标注 ===')
    
    # 1. 总体状态
    total_invites = db.query(models.Invite).count()
    total_accounts = db.query(models.Account).count()
    active_invites = db.query(models.Invite).filter(models.Invite.cleaned == False).count()
    cleaned_invites = db.query(models.Invite).filter(models.Invite.cleaned == True).count()
    
    print(f'总账户数: {total_accounts}')
    print(f'总邀请记录: {total_invites}')
    print(f'活跃记录: {active_invites}')
    print(f'已清理记录: {cleaned_invites}')
    print(f'理论最大记录: {total_accounts} × 22 = {total_accounts * 22}')
    
    # 2. 检查异常账户
    print(f'\n=== 🚨 异常账户分析 (需要手动处理) ===')
    accounts = db.query(models.Account).all()
    
    normal_accounts = []
    minor_issues = []
    major_issues = []
    
    for account in accounts:
        invite_count = db.query(models.Invite).filter(models.Invite.account_id == account.id).count()
        active_count = db.query(models.Invite).filter(
            models.Invite.account_id == account.id,
            models.Invite.cleaned == False
        ).count()
        
        # 计算真实的活跃邀请数
        manager = InviteStatusManager()
        real_active_count = manager.calculate_invites_sent(db, account)
        
        # 检查计数一致性
        count_consistent = (account.invites_sent == real_active_count)
        
        account_info = {
            'email': account.email,
            'total_records': invite_count,
            'active_records': active_count,
            'real_active': real_active_count,
            'cached_count': account.invites_sent,
            'count_consistent': count_consistent,
            'over_limit': invite_count > 22,
            'quota_used': f'{real_active_count}/22'
        }
        
        # 分类账户
        if invite_count > 22:
            major_issues.append(account_info)
        elif not count_consistent or invite_count == 0:
            minor_issues.append(account_info)
        else:
            normal_accounts.append(account_info)
    
    # 3. 报告异常账户
    if major_issues:
        print(f'\n🔴 严重异常账户 ({len(major_issues)}个) - 需要优先处理:')
        for acc in major_issues:
            print(f"  {acc['email']}:")
            print(f"    - 总记录: {acc['total_records']}条 (超出限制)")
            print(f"    - 活跃邀请: {acc['real_active']}/22")
            print(f"    - 缓存计数一致性: {'✅' if acc['count_consistent'] else '❌'}")
    
    if minor_issues:
        print(f'\n🟡 轻微异常账户 ({len(minor_issues)}个):')
        for acc in minor_issues:
            issues = []
            if not acc['count_consistent']:
                issues.append('计数不一致')
            if acc['total_records'] == 0:
                issues.append('无邀请记录')
            
            print(f"  {acc['email']}: {', '.join(issues)}")
            print(f"    - 配额: {acc['quota_used']}")
    
    print(f'\n✅ 正常账户: {len(normal_accounts)}个')
    
    # 4. 整体健康度评估
    total_issues = len(major_issues) + len(minor_issues)
    health_score = (len(normal_accounts) / total_accounts) * 100
    
    print(f'\n=== 📊 系统健康度评估 ===')
    print(f'健康度得分: {health_score:.1f}%')
    print(f'正常账户: {len(normal_accounts)}/{total_accounts}')
    print(f'需要处理的异常: {total_issues}个')
    
    if health_score >= 80:
        print('✅ 系统状态良好')
    elif health_score >= 60:
        print('⚠️ 系统状态一般，建议处理异常账户')
    else:
        print('🚨 系统状态较差，需要立即处理异常账户')
    
    return {
        'normal_accounts': normal_accounts,
        'minor_issues': minor_issues,
        'major_issues': major_issues,
        'health_score': health_score
    }

if __name__ == '__main__':
    analyze_final_status()