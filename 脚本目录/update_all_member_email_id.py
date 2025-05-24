#!/usr/bin/env python3
import requests
import time
from datetime import datetime

# 配置
API_BASE = "http://127.0.0.1:8000/api/v1"
PAGE_SIZE = 100
LOG_FILE = "update_email_ids.log"

def fetch_accounts(page: int):
    """获取一页账户列表"""
    resp = requests.get(f"{API_BASE}/accounts", params={"page": page, "size": PAGE_SIZE})
    resp.raise_for_status()
    return resp.json()

def update_email_ids(leader_email: str):
    """调用 update_email_ids 接口"""
    resp = requests.post(f"{API_BASE}/email_ids/update", json={"leader_email": leader_email})
    try:
        data = resp.json()
    except ValueError:
        data = resp.text
    return resp.status_code, data

def main():
    page = 1
    log_lines = []

    while True:
        accounts = fetch_accounts(page)
        if not accounts:
            break
        for acct in accounts:
            email = acct["email"]
            status, result = update_email_ids(email)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if status == 200:
                log_lines.append(
                    f"{timestamp} 组长 {email}：更新成功，total_members={result['total_members']}, updated_invites={result['updated_invites']}\n"
                )
            else:
                log_lines.append(
                    f"{timestamp} 组长 {email}：更新失败，状态码={status}, 响应={result}\n"
                )
            time.sleep(0.1)  # 避免请求过快
        page += 1

    # 将日志写入文件
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.writelines(log_lines)

    print(f"已完成所有组长的邮箱 ID 更新，详情请查看 {LOG_FILE}")

if __name__ == "__main__":
    main()
