# playwright_manager.py
import asyncio
from playwright.async_api import async_playwright, Browser, BrowserContext

# 全局单例引用
_playwright = None       # Playwright 实例
_browser: Browser = None # Browser 实例

# 仅用于初始化时的互斥
_lock = asyncio.Lock()

async def get_browser() -> Browser:
    """
    返回单例的 Browser 对象。
    只在首次调用时初始化 Playwright 和 Browser，后续直接复用，无锁等待。
    """
    global _playwright, _browser

    # 先看看是否已初始化，未初始化再抢锁
    if _playwright is None or _browser is None:
        async with _lock:
            # 双重检查，防止并发两个协程都进到锁里各自初始化
            if _playwright is None:
                _playwright = await async_playwright().start()
            if _browser is None:
                _browser = await _playwright.chromium.launch(headless=True)

    return _browser

async def new_context() -> BrowserContext:
    """
    基于同一个 Browser 创建一个新的 Context（相当于无痕窗口）。
    这里不使用锁，直接拿到已经启动好的 Browser。
    """
    browser = await get_browser()
    return await browser.new_context()

async def close_browser():
    """
    程序退出时优雅关闭全局 Browser 和 Playwright。
    """
    global _playwright, _browser

    if _browser is not None:
        await _browser.close()
        _browser = None

    if _playwright is not None:
        await _playwright.stop()
        _playwright = None
