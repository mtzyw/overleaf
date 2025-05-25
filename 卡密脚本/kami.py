import requests

API = "https://overapi.shayudata.com/api/v1/cards/add"

# 单个样例，CardCreate 结构
sample = {
    "code": "abc12",
    "days": 7
}

# 一定要加 json=sample，如果你用 data=，还需要 json.dumps 并手动加头
resp = requests.post(API,
                     json=sample,
                     headers={"Content-Type": "application/json"})
print(resp.status_code, resp.text)
if resp.status_code == 422:
    print("服务器反馈 detail：", resp.json())
