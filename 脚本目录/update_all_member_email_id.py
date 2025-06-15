#!/usr/bin/env python3
import requests
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置
API_BASE = "https://overapi.shayudata.com/api/v1"
PAGE_SIZE = 100
MAX_WORKERS = 10  # 同时运行的线程数，可根据接口承载能力调整

def fetch_accounts(page: int):
    """获取一页账户列表"""
    resp = requests.get(f"{API_BASE}/accounts", params={"page": page, "size": PAGE_SIZE})
    resp.raise_for_status()
    return resp.json()

def update_email_ids(leader_email: str):
    """调用 update_email_ids 接口"""
    try:
        resp = requests.post(f"{API_BASE}/email_ids/update", json={"leader_email": leader_email})
        try:
            data = resp.json()
        except ValueError:
            data = resp.text
        return leader_email, resp.status_code, data
    except Exception as e:
        return leader_email, 500, str(e)

def process_account(email):
    """处理单个账户"""
    leader_email, status, result = update_email_ids(email)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if status == 200:
        print(f"{timestamp} 组长 {leader_email}：更新成功，total_members={result['total_members']}, updated_invites={result['updated_invites']}")
    else:
        print(f"{timestamp} 组长 {leader_email}：更新失败，状态码={status}, 响应={result}")
    time.sleep(0.1)  # 防止触发接口限流

def main():
    page = 1
    while True:
        accounts = fetch_accounts(page)
        if not accounts:
            break

        emails = [acct["email"] for acct in accounts]

        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_account, email) for email in emails]
            for future in as_completed(futures):
                pass  # 所有打印逻辑在 process_account 中完成

        page += 1

    print("已完成所有组长的邮箱 ID 更新。")

if __name__ == "__main__":
    main()
