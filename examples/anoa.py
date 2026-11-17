"""Contoh: scraping lewat browser Anoa (CDP terbatas) memakai transport raw.

Jalankan dari container/host lain:  python -m examples.anoa
Env opsional: CDP_URL, CDP_AUTH_TOKEN.
"""
import asyncio
import os

from cdp_scraper import CDPConfig, CDPSessionManager, Endpoint, Platform, Scraper

CONFIG = CDPConfig.from_env().replace(
    cdp_url=os.environ.get("CDP_URL", "http://anoa-browser:9225"),
    transport="raw",          # "websocket" / "cdp" sama saja; "auto" = Playwright dulu, lalu raw
    max_sessions=1,
)

demo = Platform(
    name="demo",
    cdp=CONFIG,
    endpoints=[Endpoint("home", url="https://example.com", api_match="/api/", parser=lambda d: [], key="id")],
)


async def smoke_test():
    manager = CDPSessionManager(CONFIG)
    print(await manager.health(deep=True))
    async with manager.session() as page:
        await page.goto("https://example.com")
        print("title:", await page.title())
        await page.screenshot("example.png")


if __name__ == "__main__":
    asyncio.run(smoke_test())
