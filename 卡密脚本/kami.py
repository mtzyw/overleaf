#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_upload_cards.py

生成 7 天和 30 天卡密，批量上传到接口，只有上传成功的才写入本地文件。
- 7 天卡：3 个小写字母 + 2 位数字
- 30 天卡：3 个小写字母 + 3 位数字
"""

import random
import string
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 配置区
API_URL        = "https://overapi.shayudata.com/api/v1/cards/add"
BATCH_SIZE     = 100   # 每批上传量
COUNT_7        = 400   # 要生成的 7 天卡数量
COUNT_30       = 0    # 要生成的 30 天卡数量
OUT_SUCCESS_7  = "codes_7days_success.txt"
OUT_SUCCESS_30 = "codes_30days_success.txt"
MAX_WORKERS    = 5     # 并发线程数

def generate_codes(prefix_letters: int, suffix_digits: int, count: int):
    """
    通用卡密生成函数，去重保证不重复
    prefix_letters: 前缀字母数量（小写）
    suffix_digits: 后缀数字数量
    count: 生成数量
    """
    letters = string.ascii_lowercase
    digits  = string.digits
    codes = set()
    while len(codes) < count:
        part1 = ''.join(random.choices(letters, k=prefix_letters))
        part2 = ''.join(random.choices(digits,  k=suffix_digits))
        codes.add(part1 + part2)
    return list(codes)

def post_batch(batch_codes, days):
    """
    向 API 提交一批卡密。成功返回该批次的 codes 列表，失败抛出异常。
    """
    payload = [{"code": code, "days": days} for code in batch_codes]
    resp = requests.post(API_URL, json=payload, timeout=15)
    resp.raise_for_status()
    return batch_codes  # 整批视为成功

def upload_and_collect(codes, days):
    """
    多线程批量上传，返回上传成功的 codes 列表。
    """
    total = len(codes)
    print(f"\n开始上传 {total} 条 {days} 天卡密，分批 {BATCH_SIZE} 条，并发 {MAX_WORKERS} 线程")
    # 拆分批次
    batches = [codes[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    success_codes = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_batch = {executor.submit(post_batch, batch, days): batch for batch in batches}
        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                uploaded = future.result()
                success_codes.extend(uploaded)
                print(f"  ✔ 成功上传批次 {batch[0]}…({len(batch)} 条)")
            except Exception as exc:
                print(f"  ❌ 上传失败批次 {batch[0]}…({len(batch)} 条) 错误：{exc}")
    print(f"{days} 天卡上传完成，共 {len(success_codes)}/{total} 条成功")
    return success_codes

def save_codes(codes, filename):
    """
    将卡密列表保存到指定文件，每行一个
    """
    with open(filename, 'w', encoding='utf-8') as f:
        for code in codes:
            f.write(f"https://overleaf.shayudata.com/{code}\n")
    print(f"已保存 {len(codes)} 条成功卡密到 {filename}")

def main():
    # 确保当前目录可写
    os.makedirs(os.getcwd(), exist_ok=True)

    # 1. 生成卡密
    codes7  = generate_codes(prefix_letters=3, suffix_digits=2, count=COUNT_7)
    codes30 = generate_codes(prefix_letters=3, suffix_digits=3, count=COUNT_30)
    print(f"\n生成卡密：{len(codes7)} 条 7 天 / {len(codes30)} 条 30 天")

    # 2. 上传并收集成功列表
    success7  = upload_and_collect(codes7, days=7)
    success30 = upload_and_collect(codes30, days=30)

    # 3. 保存只有上传成功的卡密
    save_codes(success7, OUT_SUCCESS_7)
    save_codes(success30, OUT_SUCCESS_30)

if __name__ == "__main__":
    main()
