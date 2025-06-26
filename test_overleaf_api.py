#!/usr/bin/env python3
"""
测试Overleaf API获取
"""
import sys
import os
import requests
import re
import html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import SessionLocal
import models

def test_overleaf_request():
    """测试获取Overleaf成员页面"""
    db = SessionLocal()
    try:
        # 获取测试账户
        account = db.query(models.Account).filter(
            models.Account.email == "ezkcuwl266@hotmail.com"
        ).first()
        
        if not account:
            print("测试账户不存在")
            return
        
        print(f"测试账户: {account.email}")
        print(f"组ID: {account.group_id}")
        print(f"Session Cookie: {account.session_cookie[:50] if account.session_cookie else 'None'}...")
        
        # 创建session
        session = requests.Session()
        if account.session_cookie:
            session.cookies.set(
                "overleaf_session2", account.session_cookie,
                domain=".overleaf.com", path="/"
            )
        
        # 请求成员页面
        members_url = f"https://www.overleaf.com/manage/groups/{account.group_id}/members"
        print(f"请求URL: {members_url}")
        
        resp = session.get(members_url, headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "max-age=0",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        })
        
        print(f"响应状态: {resp.status_code}")
        print(f"响应长度: {len(resp.text)}")
        
        # 查找ol-users meta标签
        meta_pattern = r'<meta\s+name="ol-users"[^>]*content="([^"]*)"'
        match = re.search(meta_pattern, resp.text)
        
        if match:
            print("✓ 找到ol-users meta标签")
            users_content = html.unescape(match.group(1))
            print(f"用户数据长度: {len(users_content)}")
            print(f"用户数据预览: {users_content[:200]}...")
            
            # 尝试解析JSON
            import json
            try:
                users_data = json.loads(users_content)
                print(f"✓ JSON解析成功，用户数量: {len(users_data)}")
                
                # 显示前几个用户
                for i, user in enumerate(users_data[:3]):
                    print(f"  用户{i+1}: email={user.get('email', 'N/A')}, _id={user.get('_id', 'N/A')}")
                    
            except json.JSONDecodeError as e:
                print(f"❌ JSON解析失败: {e}")
                
        else:
            print("❌ 未找到ol-users meta标签")
            
            # 查找其他可能的meta标签
            all_meta = re.findall(r'<meta\s+name="([^"]*)"', resp.text)
            print(f"找到的meta标签: {all_meta[:10]}")
            
            # 保存HTML到文件调试
            with open("debug_response.html", "w", encoding="utf-8") as f:
                f.write(resp.text)
            print("已保存响应到 debug_response.html")
            
    finally:
        db.close()

if __name__ == "__main__":
    test_overleaf_request()