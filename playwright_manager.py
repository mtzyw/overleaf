# playwright_manager.py

import asyncio
from playwright.async_api import async_playwright, Browser, BrowserContext

_playwright = None       # 全局 Playwright 实例
_browser: Browser = None  # 全局 Browser 实例
_lock = asyncio.Lock()    # 防止并发初始化

async def get_browser() -> Browser:
    """
    返回单例的 Browser 对象，首次调用时启动 Playwright 并 launch。
    """
    global _playwright, _browser
    async with _lock:
        if _playwright is None:
            _playwright = await async_playwright().start()
        if _browser is None:
            _browser = await _playwright.chromium.launch(headless=True)
    return _browser

async def new_context() -> BrowserContext:
    """
    从单例 Browser 中创建一个新的 Context（相当于无痕窗口）。
    """
    browser = await get_browser()
    return await browser.new_context()

async def close_browser():
    """
    程序退出时调用，优雅关闭 Playwright 和其 Browser 实例。
    """
    global _playwright, _browser

    # 先关闭 BrowserContext 进程
    if _browser is not None:
        await _browser.close()
        _browser = None

    # 再关闭 Playwright 本身
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None
