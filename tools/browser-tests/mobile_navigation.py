"""Keyboard focus checks for the built application's mobile navigation."""

import os

from playwright.sync_api import expect, sync_playwright


BASE = os.getenv("CSI_BROWSER_BASE_URL", "http://127.0.0.1:8088")


def inside_dialog(page):
    return page.evaluate(
        "document.activeElement?.closest('dialog, [role=dialog]')?.getAttribute('aria-label') === 'Navigate'"
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width in (320, 375, 767):
        page = browser.new_page(viewport={"width": width, "height": 812})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE, wait_until="networkidle")
        page.get_by_label("Login ID").fill("fixture-f09")
        page.get_by_label("Password").fill("fixture-only-password")
        page.get_by_role("button", name="Sign in").click()
        expect(page.locator(".account-button")).to_be_visible()
        opener = page.get_by_role("button", name="Open navigation")
        opener.click()
        dialog = page.get_by_role("dialog", name="Navigate")
        expect(dialog).to_be_visible()
        assert inside_dialog(page), width
        for _ in range(12):
            page.keyboard.press("Tab")
            assert inside_dialog(page), (
                width,
                "Tab",
                page.evaluate("document.activeElement?.outerHTML"),
            )
        for _ in range(12):
            page.keyboard.press("Shift+Tab")
            assert inside_dialog(page), (
                width,
                "Shift+Tab",
                page.evaluate("document.activeElement?.outerHTML"),
            )
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        expect(opener).to_have_attribute("aria-expanded", "false")
        expect(opener).to_be_focused()
        page.keyboard.press("Tab")
        expect(page.locator(".account-button")).to_be_focused()
        opener.click()
        dialog.get_by_role("button", name="Close navigation").click()
        expect(dialog).to_be_hidden()
        expect(opener).to_be_focused()
        opener.click()
        dialog.get_by_role("button", name="Transactions").click()
        expect(page.locator(".transaction-explorer")).to_be_visible()
        expect(opener).to_be_focused()
        opener.click()
        assert inside_dialog(page), width
        page.keyboard.press("Escape")
        expect(opener).to_be_focused()
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (
            width
        )
        assert not errors, (width, errors)
        page.close()
    tablet = browser.new_page(viewport={"width": 768, "height": 900})
    tablet.goto(BASE, wait_until="networkidle")
    tablet.get_by_label("Login ID").fill("fixture-f09")
    tablet.get_by_label("Password").fill("fixture-only-password")
    tablet.get_by_role("button", name="Sign in").click()
    expect(tablet.locator(".main-nav")).to_be_visible()
    expect(tablet.get_by_role("button", name="Open navigation")).to_be_hidden()
    browser.close()

print("Mobile navigation focus passed at 320, 375, 767 and 768px")
