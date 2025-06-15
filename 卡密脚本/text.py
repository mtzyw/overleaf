import asyncio
import httpx
import random
import time
import string

SOCKS5_PROXY = "socks5://0D45laKzPT-zone-marstop-region:28303939@as.678ca161f181c956.ipmars.vip:4900"
PROXIES = {
    "http://": SOCKS5_PROXY,
    "https://": SOCKS5_PROXY
}


async def test_socks5_connectivity():
    print("🧪 [步骤①] 正在检测 SOCKS5 代理连接状态...")
    test_url = "http://httpbin.org/ip"
    try:
        async with httpx.AsyncClient(proxies=PROXIES, timeout=10) as client:
            response = await client.get(test_url)
            ip = response.json().get("origin", "未知IP")
            print(f"✅ SOCKS5 代理已连接成功，当前出口 IP: {ip}")
            return True
    except Exception as e:
        print(f"❌ SOCKS5 代理连接失败: {e}")
        return False


def generate_random_params():
    session_id = random.randint(-9999999999999999999, 9999999999999999999)
    request_id = random.randint(100000, 999999)
    language = random.choice(['en', 'en-US', 'zh-CN', 'ja', 'fr', 'de'])
    print(f"🔧 会话ID: {session_id}，请求ID: {request_id}，语言: {language}")
    return session_id, request_id, language


def generate_random_cookies():
    nid_str = ''.join(random.choices(string.ascii_letters + string.digits + '-_', k=150))
    nid = f"NID={random.randint(500, 600)}={nid_str}"
    timestamp = int(time.time())
    ga1 = f"*ga=GA1.1.{random.randint(100000000, 999999999)}.{timestamp}"
    ga2 = f"*ga*KHZNC1Q6K0=GS2.1.s{timestamp}$o1$g0$t{timestamp}$j60$l0$h0"
    otz = f"OTZ={random.randint(8100000, 8200000)}*24_24__24_"
    print(f"🍪 已生成随机 Cookie")
    return f"{nid}; {ga2}; {ga1}; {otz}"


def generate_random_ua():
    chrome_ver = f"{random.randint(120, 140)}.0.{random.randint(7000, 8000)}.{random.randint(0, 99)}"
    chrome_major = chrome_ver.split('.')[0]
    webkit_ver = f"537.{random.randint(30, 40)}"
    user_agent = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/{webkit_ver} (KHTML, like Gecko) Chrome/{chrome_ver} Safari/{webkit_ver}"
    sec_ch_ua = f'"Google Chrome";v="{chrome_major}", "Chromium";v="{chrome_major}", "Not/A)Brand";v="{random.choice([8, 24, 99])}"'
    print(f"🧭 使用 User-Agent: {user_agent}")
    return user_agent, sec_ch_ua, chrome_ver


async def make_request_with_proxy(extension_id='pnnpcpknggelkmjmfinmopagjjckffga'):
    print("=" * 60)
    print("🚀 正在发起请求...")

    if not await test_socks5_connectivity():
        print("⚠️ 中止请求：代理不可用")
        return

    session_id, request_id, language = generate_random_params()
    user_agent, sec_ch_ua, chrome_version = generate_random_ua()
    cookies = generate_random_cookies()

    url = f"https://chromewebstore.google.com/_/ChromeWebStoreConsumerFeUi/data/batchexecute?" \
          f"rpcids=xY2Ddd%2CGApdCe&source-path=%2Fdetail%2Fhigh-contrast-mode-dark-m%2F{extension_id}" \
          f"&f.sid={session_id}&bl=boq_chrome-webstore-consumerfe-ui_20250602.07_p0" \
          f"&hl={language}&soc-app=1&soc-platform=1&soc-device=1&_reqid={request_id}&rt=c"

    headers = {
        "accept": "*/*",
        "accept-language": language,
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-full-version": f'"{chrome_version}"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-same-domain": "1",
        "cookie": cookies,
        "Referer": "https://chromewebstore.google.com/",
        "User-Agent": user_agent
    }

    body = f"f.req=%5B%5B%5B%22xY2Ddd%22%2C%22%5B%5C%22{extension_id}%5C%22%5D%22%2Cnull%2C%221%22%5D%2C" \
           f"%5B%22GApdCe%22%2C%22%5B%5C%22{extension_id}%5C%22%5D%22%2Cnull%2C%223%22%5D%5D%5D&"

    try:
        print("📡 正在请求 Chrome 插件详情接口...")
        async with httpx.AsyncClient(proxies=PROXIES, timeout=30) as client:
            response = await client.post(url, headers=headers, content=body)
            print(f"✅ 请求成功，状态码: {response.status_code}")
            print(f"📦 响应前200字符: {response.text[:200]}...")
    except Exception as e:
        print(f"❌ 请求失败: {e}")


# === 主函数入口 ===
if __name__ == "__main__":
    asyncio.run(make_request_with_proxy())
