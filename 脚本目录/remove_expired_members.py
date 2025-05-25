#!/usr/bin/env python3
import requests
import time
from datetime import datetime

# 配置区
API_BASE = "https://overapi.shayudata.com/api/v1"
PAGE_SIZE = 100

def fetch_invites(page: int):
    """获取一页邀请记录"""
    resp = requests.get(
        f"{API_BASE}/invite/records",
        params={"page": page, "size": PAGE_SIZE},
        timeout=10
    )
    resp.raise_for_status()
    return resp.json()

def remove_member(email: str):
    """调用后台删除成员接口"""
    resp = requests.post(
        f"{API_BASE}/member/remove",
        json={"email": email},
        timeout=10
    )
    return resp.status_code, resp.text

def main():
    now_ts = int(time.time())
    page = 1

    while True:
        try:
            invites = fetch_invites(page)
        except Exception as e:
            print(f"{datetime.now()} 第 {page} 页获取失败: {e}")
            break

        if not invites:
            print("所有记录已处理完毕。")
            break

        for inv in invites:
            if inv["expires_at"] < now_ts:
                email = inv["email"]
                status_code, resp_text = remove_member(email)
                t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if status_code in (200, 204):
                    print(f"{t} 过期邀请({inv['id']}) 邮箱 {email} 删除成功")
                else:
                    print(f"{t} 过期邀请({inv['id']}) 邮箱 {email} 删除失败: [{status_code}] {resp_text}")
        page += 1

    print("清理完成。")

if __name__ == "__main__":
    main()
