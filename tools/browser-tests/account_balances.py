"""Posted-balance UI checks against a disposable fixture Compose project."""

import os

from playwright.sync_api import expect, sync_playwright


BASE = os.getenv("CSI_BROWSER_BASE_URL", "http://127.0.0.1:8088")
WIDTHS = (320, 360, 375, 390, 414, 430, 599, 600, 768, 820, 834,
          839, 840, 841, 1024, 1180, 1280, 1440, 1600)


def sign_in(browser, fixture):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE, wait_until="networkidle")
    page.get_by_label("Login ID").fill(fixture)
    page.get_by_label("Password").fill("fixture-only-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Your accounts")).to_be_visible()
    return page, errors


def check_text_resize(page):
    page.evaluate("""() => {
      const sizes = [...document.querySelectorAll('*')]
        .map(el => [el, parseFloat(getComputedStyle(el).fontSize)]);
      for (const [el, size] of sizes)
        if (size && !['SCRIPT', 'STYLE'].includes(el.tagName))
          el.style.fontSize = `${size * 2}px`;
    }""")
    for width in (320, 360, 375, 430, 600, 640, 767, 768, 820, 840, 1024):
        page.set_viewport_size({"width": width, "height": 900})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page, errors = sign_in(browser, "fixture-f01")
    options = page.locator(".account-option")
    expect(options).to_have_count(3)
    expect(options.nth(0)).to_contain_text("R25,650.00")
    expect(options.nth(1)).to_contain_text("R22,150.00")
    expect(options.nth(2)).to_contain_text("R3,500.00")
    expect(page.locator(".accounts-overview")).to_contain_text("31 Oct 2026")
    assert page.locator(".accounts-overview select").count() == 0
    page.get_by_role("radio", name="Everyday").check()
    expect(page.locator(".summary-card.primary .metric-value")).to_have_text("R850.00")
    assert page.get_by_role("radio", name="Everyday").is_checked()
    page.locator(".main-nav").get_by_role("button", name="Transactions").click()
    expect(page.locator(".selected-balance")).to_contain_text("R22,150.00")
    expect(page.locator(".selected-balance")).to_contain_text("31 Oct 2026")
    expect(page.get_by_role("combobox", name="Account", exact=True)).to_have_value("f01-everyday")
    page.get_by_role("combobox", name="Account", exact=True).select_option("")
    expect(page.locator(".selected-balance")).to_contain_text("R25,650.00")
    page.locator(".main-nav").get_by_role("button", name="Overview").click()
    assert page.get_by_role("radio", name="All accounts").is_checked()
    page.get_by_role("button", name="Hide amounts").click()
    assert "R25,650.00" not in page.locator("body").inner_text()
    assert "R22,150.00" not in page.locator("body").inner_text()
    assert "R3,500.00" not in page.locator("body").inner_text()
    assert "R25,650.00" not in page.locator("body").aria_snapshot()
    page.locator(".main-nav").get_by_role("button", name="Transactions").click()
    assert "R25,650.00" not in page.locator("body").inner_text()
    page.get_by_role("button", name="Show amounts").click()

    for width in WIDTHS:
        page.set_viewport_size({"width": width, "height": 900})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
        balance = page.locator(".selected-balance-amount strong")
        expect(balance).to_contain_text("R25,650.00")
        assert balance.evaluate("el => { const r=el.getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth && el.scrollWidth<=el.clientWidth+1 }"), width
        assert page.get_by_role("combobox", name="Account", exact=True).is_visible(), width
        if width <= 767:
            page.locator(".bottom-nav").get_by_role("button", name="Overview").click()
        else:
            page.locator(".main-nav").get_by_role("button", name="Overview").click()
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
        expect(page.locator(".account-option-amount")).to_have_count(3)
        for amount in page.locator(".account-option-amount").all():
            assert amount.evaluate("el => { const r=el.getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth && el.scrollWidth<=el.clientWidth+1 }"), width
        if width <= 767:
            page.locator(".bottom-nav").get_by_role("button", name="Transactions").click()
        else:
            page.locator(".main-nav").get_by_role("button", name="Transactions").click()
    for width, height in ((667, 375), (844, 390), (1024, 768)):
        page.set_viewport_size({"width": width, "height": height})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (width, height)
    # A 640px window at 200% browser zoom has a 320px CSS viewport.
    page.set_viewport_size({"width": 320, "height": 900})
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    page.get_by_role("combobox", name="Account", exact=True).focus()
    expect(page.get_by_role("combobox", name="Account", exact=True)).to_be_focused()
    check_text_resize(page)
    page.reload(wait_until="networkidle")
    page.set_viewport_size({"width": 1024, "height": 900})
    page.locator(".main-nav").get_by_role("button", name="Overview").click()
    expect(page.get_by_role("heading", name="Your accounts")).to_be_visible()
    check_text_resize(page)
    page.close()
    assert not errors, errors

    period, period_errors = sign_in(browser, "fixture-f14")
    expect(period.locator(".account-option")).to_have_count(2)
    expect(period.locator(".account-option-amount").first).to_have_text("R10,000.00")
    period.get_by_label("From", exact=True).fill("2026-09-01")
    period.get_by_label("To", exact=True).fill("2026-09-30")
    period.get_by_role("button", name="Apply period").click()
    expect(period.locator(".summary-card").last).to_contain_text("+R7,000.00")
    expect(period.locator(".account-option-amount").first).to_have_text("R10,000.00")
    expect(period.locator(".accounts-overview")).to_contain_text("31 Oct 2026")
    period.close()
    assert not period_errors, period_errors

    for fixture, count in (("fixture-empty", 0), ("fixture-closed", 0),
                           ("fixture-f17", 2)):
        customer, customer_errors = sign_in(browser, fixture)
        if count:
            expect(customer.locator(".account-option")).to_have_count(count + 1)
            expect(customer.locator(".account-option").first).to_contain_text("−R50.00")
            expect(customer.locator(".account-option").nth(1)).to_contain_text("−R50.00")
            expect(customer.locator(".account-option").nth(2)).to_contain_text("R0.00")
        else:
            expect(customer.locator(".accounts-empty")).to_contain_text("No open accounts")
            assert "R0.00" not in customer.locator(".accounts-overview").inner_text()
        customer.close()
        assert not customer_errors, (fixture, customer_errors)

    failure, failure_errors = sign_in(browser, "fixture-f01")
    failure.route("**/api/v1/accounts", lambda route: route.abort())
    failure.get_by_role("button", name="Refresh data").click()
    expect(failure.get_by_text("Account balances could not be refreshed. Retry when ready.")).to_be_visible()
    assert failure.locator(".account-option-amount").count() == 0
    failure.close()
    assert not failure_errors, failure_errors
    browser.close()

print(f"Balance browser checks passed across {len(WIDTHS)} widths, landscape and zoom")
