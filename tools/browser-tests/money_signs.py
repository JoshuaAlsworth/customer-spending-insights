"""Signed Money out and privacy checks against real fixture summaries."""

import os

from playwright.sync_api import expect, sync_playwright


BASE = os.getenv("CSI_BROWSER_BASE_URL", "http://127.0.0.1:8088")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width in (375, 1280):
        for fixture, day, expected in (
            ("fixture-f01", None, "+R850.00"),
            ("fixture-f09", "2026-10-28", "−R120.00"),
            ("fixture-f01", "2026-10-01", "R0.00"),
        ):
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(BASE, wait_until="networkidle")
            page.get_by_label("Login ID").fill(fixture)
            page.get_by_label("Password").fill("fixture-only-password")
            page.get_by_role("button", name="Sign in").click()
            if day:
                page.locator(".period-picker summary").click()
                page.get_by_role("button", name="Custom dates").click()
                page.get_by_label("From", exact=True).fill(day)
                page.get_by_label("To", exact=True).fill(day)
                page.get_by_role("button", name="Apply period").click()
            metric = page.locator(".summary-card.primary .metric-value")
            expect(metric).to_have_text(expected)
            if expected.startswith("−"):
                expect(
                    page.locator(".summary-card.primary .metric-note")
                ).to_contain_text("Refunds exceeded posted outgoings")
            page.get_by_role("button", name="Hide amounts").click()
            expect(metric).to_have_text("••••")
            assert expected not in page.locator("body").aria_snapshot(), (
                width,
                fixture,
                day,
            )
            page.get_by_role("button", name="Show amounts").click()
            expect(metric).to_have_text(expected)
            assert not page.evaluate(
                "document.documentElement.scrollWidth > innerWidth"
            )
            assert not errors, (width, fixture, day, errors)
            page.close()
    browser.close()

print(
    "Signed Money out, refund-only, zero and privacy passed at mobile and desktop widths"
)
