"""Helper browser yang dipakai banyak scraper."""


async def close_login_modal(page):
    try:
        await page.evaluate("""() => {
            document.querySelectorAll('[data-e2e="modal-close-inner-button"], div[class*="ModalClose"]')
                .forEach(btn => btn.click());
        }""")
    except Exception:
        pass
