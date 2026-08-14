from playwright.sync_api import sync_playwright

def test_rtx():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        c = b.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        p = c.new_page()
        p.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        r = p.goto("https://careers.rtx.com/global/en/collins-aerospace-search-results-general", wait_until="domcontentloaded", timeout=30000)
        print("Status:", r.status if r else "None")
        p.wait_for_timeout(3000)
        print("Title:", p.title())

if __name__ == "__main__":
    test_rtx()
