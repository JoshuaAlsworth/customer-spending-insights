"""Chart-to-history category actions against the built application."""

import os
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


BASE = os.getenv("CSI_BROWSER_BASE_URL", "http://127.0.0.1:8088")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: requests.append(request.url)
        if "/api/v1/transactions?" in request.url
        else None,
    )
    page.goto(BASE, wait_until="networkidle")
    page.get_by_label("Login ID").fill("fixture-f09")
    page.get_by_label("Password").fill("fixture-only-password")
    page.get_by_role("button", name="Sign in").click()
    summary = page.locator(".summary-card.primary .metric-value")
    expect(summary).to_have_text("+R12,480.50")
    account = page.locator(".account-button").inner_text()
    period = page.locator(".period-control .select-button").inner_text()

    def select_chart(name, code):
        page.get_by_role("button", name=f"Filter transactions by {name}").click()
        expect(page.locator(".transaction-explorer")).to_be_visible()
        expect(page.get_by_label("Category")).to_have_value(code)
        selected = parse_qs(urlparse(requests[-1]).query)
        assert selected.get("category") == [code], selected
        assert "cursor" not in selected, selected

    select_chart("Groceries", "GROCERIES")
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_role("button", name="Reset filters").click()
    expect(page.get_by_label("Category")).to_have_value("")
    page.locator(".sidebar-nav").get_by_role("button", name="Overview").click()
    expect(summary).to_have_text("+R12,480.50")
    select_chart("Groceries", "GROCERIES")
    page.locator(".sidebar-nav").get_by_role("button", name="Overview").click()
    select_chart("Health", "HEALTH")
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_label("Status").select_option("PENDING")
    expect(page.get_by_text("No transactions match these filters.")).to_be_visible()
    page.locator(".transaction-filter-menu summary").click()
    page.locator(".sidebar-nav").get_by_role("button", name="Overview").click()
    select_chart("Health", "HEALTH")
    expect(page.get_by_label("Status")).to_have_value("PENDING")
    expect(page.get_by_text("No transactions match these filters.")).to_be_visible()
    assert page.locator(".account-button").inner_text() == account
    assert page.locator(".period-control .select-button").inner_text() == period
    page.locator(".sidebar-nav").get_by_role("button", name="Overview").click()
    expect(summary).to_have_text("+R12,480.50")
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    assert not errors, errors
    browser.close()

print("Repeated category activation, scope, cursor and pending-filter checks passed")
