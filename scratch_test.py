from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    try:
        response = page.goto('https://careers.rtx.com/global/en/collins-aerospace-search-results-general', wait_until='domcontentloaded')
        print('Status:', response.status)
    except Exception as e:
        print('Error:', e)
