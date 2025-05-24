# overleaf_utils.py

import re
import requests
from playwright_manager import new_context
from yescaptcha.client import Client
from yescaptcha.task import NoCaptchaTaskProxyless
from settings import settings

async def get_tokens() -> tuple[str, str]:
    """
    使用复用的 BrowserContext 获取 _csrf 和 overleaf_session2。
    """
    ctx = await new_context()
    page = await ctx.new_page()
    await page.goto(settings.LOGIN_URL)
    csrf = await page.eval_on_selector("input[name='_csrf']", "el => el.value")
    cookies = await ctx.cookies()
    sess = next(c["value"] for c in cookies if c["name"] == "overleaf_session2")
    await ctx.close()
    return csrf, sess

def get_captcha_token() -> str:
    client = Client(client_key=settings.YESCAPTCHA_KEY, debug=False)
    task = NoCaptchaTaskProxyless(
        website_key=settings.SITE_KEY,
        website_url=settings.LOGIN_URL
    )
    job = client.create_task(task)
    return job.get_solution()["gRecaptchaResponse"]

def perform_login(
    csrf: str,
    session_cookie: str,
    email: str,
    pwd: str,
    captcha: str
) -> requests.Session:
    s = requests.Session()
    s.cookies.set("overleaf_session2", session_cookie, domain=".overleaf.com", path="/")
    s.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": settings.LOGIN_URL,
        "Origin": "https://www.overleaf.com",
        "User-Agent": "Mozilla/5.0"
    })
    # 预请求，可能跳过验证码
    s.post("https://www.overleaf.com/login/can-skip-captcha", json={"email": email})
    # 真正登录
    s.post(settings.LOGIN_URL, json={
        "_csrf": csrf,
        "email": email,
        "password": pwd,
        "g-recaptcha-response": captcha
    })
    return s

def refresh_session(session: requests.Session, csrf: str) -> str:
    resp = session.post(
        "https://www.overleaf.com/event/loads_v2_dash",
        json={"page": "/project", "_csrf": csrf},
        headers={
            "Content-Type":"application/json; charset=utf-8",
            "Accept":"application/json",
            "Referer":"https://www.overleaf.com/project",
            "Origin":"https://www.overleaf.com",
            "User-Agent":"Mozilla/5.0"
        }
    )
    sc = resp.headers.get("set-cookie", "")
    m = re.search(r"overleaf_session2=([^;]+)", sc)
    if m:
        return m.group(1)
    return session.cookies.get("overleaf_session2")

def get_new_csrf(session: requests.Session, group_id: str) -> str:
    resp = session.get(
        f"https://www.overleaf.com/manage/groups/{group_id}/members",
        headers={
            "Accept":"text/html,application/xhtml+xml",
            "Referer":"https://www.overleaf.com/project",
            "User-Agent":"Mozilla/5.0"
        }
    )
    m = re.search(r'<meta name="ol-csrfToken" content="([^"]+)"', resp.text)
    if not m:
        raise RuntimeError("提取 CSRF 失败")
    return m.group(1)
