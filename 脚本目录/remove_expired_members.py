#!/usr/bin/env python3
import requests
import time
from datetime import datetime

# 配置区
API_BASE = "http://127.0.0.1:8000/api/v1"
PAGE_SIZE = 100
LOG_FILE = "expired_invites_cleanup.log"

def fetch_invites(page: int):
    """获取一页邀请记录"""
    resp = requests.get(f"{API_BASE}/invite/records", params={"page": page, "size": PAGE_SIZE})
    resp.raise_for_status()
    return resp.json()

def remove_member(email: str):
    """调用后台删除成员接口"""
    resp = requests.post(f"{API_BASE}/member/remove", json={"email": email})
    # 如果后台接口是 /api/v1/member/remove，请根据实际改
    return resp.status_code, resp.text

def main():
    now_ts = int(time.time())
    page = 1
    log_lines = []

    while True:
        invites = fetch_invites(page)
        if not invites:
            break

        for inv in invites:
            if inv["expires_at"] < now_ts:
                email = inv["email"]
                code, text = remove_member(email)
                t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if code in (200, 204):
                    log_lines.append(f"{t} 过期邀请({inv['id']}) 邮箱 {email} 删除成功\n")
                else:
                    log_lines.append(f"{t} 过期邀请({inv['id']}) 邮箱 {email} 删除失败: [{code}] {text}\n")
        page += 1

    # 写日志
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.writelines(log_lines)

    print(f"清理完成，日志已写入 {LOG_FILE}")

if __name__ == "__main__":
    main()
