#!/usr/bin/env python3
import requests
from datetime import datetime

# 配置区
API_BASE = "https://overapi.shayudata.com/api/v1"

def cleanup_expired_members(delete_records=True):
    """调用批量清理过期成员接口"""
    resp = requests.post(
        f"{API_BASE}/maintenance/cleanup_expired",
        params={
            "delete_records": delete_records,
            "limit": 100
        },
        timeout=30  # 批量处理可能需要更长时间
    )
    return resp.status_code, resp.json() if resp.status_code == 200 else resp.text

def main():
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 开始清理过期邀请...")
    
    try:
        status_code, result = cleanup_expired_members()
        
        if status_code == 200:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 清理完成:")
            print(f"  - 总清理记录: {result['cleaned']}")
            if 'stats' in result and result['stats']:
                stats = result['stats']
                print(f"  - 找到过期记录: {stats.get('total_found', 0)}")
                print(f"  - 已接受成员删除: {stats.get('accepted_removed', 0)}")
                print(f"  - 未接受邀请撤销: {stats.get('pending_revoked', 0)}")
                print(f"  - 真正删除记录: {stats.get('deleted_records', 0)}")
                print(f"  - 错误数量: {stats.get('errors', 0)}")
        else:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 清理失败: [{status_code}] {result}")
            
    except Exception as e:
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 清理异常: {e}")

if __name__ == "__main__":
    main()
