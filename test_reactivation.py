#!/usr/bin/env python3
"""
测试卡密重新激活功能
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import crud
import models
from database import SessionLocal, engine, Base
import time
from datetime import datetime, timedelta

def setup_test_db():
    """设置测试数据库"""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # 清理测试数据
    db.query(models.Invite).delete()
    db.query(models.Card).delete() 
    db.query(models.Account).delete()
    db.commit()
    
    return db

def test_reactivation_logic():
    """测试重新激活逻辑"""
    print("🧪 开始测试卡密重新激活功能")
    
    db = setup_test_db()
    
    try:
        # 1. 创建测试数据
        print("\n1️⃣ 创建测试数据...")
        
        # 创建账户
        account_a = crud.create_account(db, "test_a@example.com", "password123", "group_a", 100)
        account_b = crud.create_account(db, "test_b@example.com", "password123", "group_b", 100)
        print(f"✅ 创建账户: {account_a.email} (ID: {account_a.id}), {account_b.email} (ID: {account_b.id})")
        
        # 创建卡密
        card = crud.create_card(db, "TEST123", 30)
        print(f"✅ 创建卡密: {card.code} (30天)")
        
        # 2. 测试新卡密验证
        print("\n2️⃣ 测试新卡密验证...")
        new_card = crud.get_card(db, "TEST123")
        assert new_card is not None, "新卡密应该可用"
        print("✅ 新卡密验证通过")
        
        # 3. 模拟第一次邀请
        print("\n3️⃣ 模拟第一次邀请...")
        now_ts = int(time.time())
        expires_ts = now_ts + (30 * 24 * 3600)  # 30天后
        
        # 创建邀请记录
        invite = crud.create_invite_record(
            db, account_a, "user@example.com", expires_ts, True, {"status": "first_invite"}, card
        )
        
        # 标记卡密已使用
        crud.mark_card_used(db, card)
        print(f"✅ 第一次邀请成功，记录ID: {invite.id}")
        
        # 4. 测试重新激活验证
        print("\n4️⃣ 测试重新激活验证...")
        
        # 测试同用户重新激活
        reactivation_card, status = crud.get_card_for_reactivation(db, "TEST123", "user@example.com")
        assert reactivation_card is not None, "同用户应该可以重新激活"
        assert status == "权益期内可重新激活", f"状态应该是可重新激活，实际是: {status}"
        print("✅ 同用户重新激活验证通过")
        
        # 测试不同用户使用已用卡密
        other_card, other_status = crud.get_card_for_reactivation(db, "TEST123", "other@example.com")
        assert other_card is None, "不同用户不应该可以使用已用卡密"
        print("✅ 不同用户使用已用卡密被正确拒绝")
        
        # 5. 测试排除账户功能
        print("\n5️⃣ 测试排除账户功能...")
        excluded_account = crud.get_available_account_exclude(db, account_a.id)
        assert excluded_account.id == account_b.id, "应该返回B账户（排除A账户）"
        print(f"✅ 排除账户功能正常，返回账户: {excluded_account.email}")
        
        # 6. 测试权益过期后的验证
        print("\n6️⃣ 测试权益过期后的验证...")
        
        # 修改邀请记录为已过期
        invite.expires_at = now_ts - 3600  # 1小时前过期
        db.commit()
        
        expired_card, expired_status = crud.get_card_for_reactivation(db, "TEST123", "user@example.com")
        assert expired_card is None, "权益过期后不应该可以重新激活"
        print("✅ 权益过期后重新激活被正确拒绝")
        
        print("\n🎉 所有测试通过！卡密重新激活功能正常工作")
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        db.close()

if __name__ == "__main__":
    success = test_reactivation_logic()
    sys.exit(0 if success else 1)