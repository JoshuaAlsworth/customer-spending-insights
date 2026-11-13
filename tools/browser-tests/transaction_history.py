"""End-to-end checks against the disposable fixture Compose project."""
import os
import subprocess
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import expect, sync_playwright

base = os.getenv("CSI_BROWSER_BASE_URL", "http://127.0.0.1:8088")
def navigate(page, target):
    width = page.viewport_size["width"]
    if width >= 1100:
        page.locator(".sidebar-nav").get_by_role("button", name=target).click()
    elif width >= 768:
        page.locator(".main-nav").get_by_role("button", name=target).click()
    else:
        page.get_by_role("button", name="Open navigation").click()
        page.locator(".mobile-menu").get_by_role("button", name=target).click()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base, wait_until="networkidle")
    page.get_by_label("Login ID").fill("fixture-f09")
    page.get_by_label("Password").fill("fixture-only-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator(".recent-table tbody tr")).to_have_count(4)
    navigate(page, "Transactions")
    expect(page.locator(".activity-table tbody tr")).to_have_count(13)
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_label("Status").select_option("PENDING")
    expect(page.locator(".activity-table tbody tr")).to_have_count(2)
    page.get_by_label("Category").select_option("GROCERIES")
    expect(page.get_by_text("No transactions match these filters.")).to_be_visible()
    page.get_by_role("button", name="Reset filters").click()
    expect(page.locator(".activity-table tbody tr")).to_have_count(13)
    page.get_by_label("Search transactions").fill("  CITYLINK  ")
    expect(page.locator(".activity-table tbody tr")).to_have_count(2)
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_role("button", name="Reset filters").click()
    page.locator(".activity-link").first.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.locator(".detail-close")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.route("**/api/v1/transactions?*", lambda route: route.abort())
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_label("Status").select_option("CANCELLED")
    expect(page.get_by_text("Transactions could not be loaded.")).to_be_visible()
    page.unroute("**/api/v1/transactions?*")
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_role("button", name="Retry").click()
    expect(page.get_by_text("No transactions match these filters.")).to_be_visible()
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_role("button", name="Reset filters").click()
    expect(page.locator(".activity-table tbody tr")).to_have_count(13)
    transaction_requests = []
    page.on("request", lambda request: transaction_requests.append(request.url) if "/api/v1/transactions?" in request.url else None)
    search_field = page.get_by_label("Search transactions")
    before_invalid = len(transaction_requests)
    search_field.fill("😀")
    expect(page.locator("#transaction-search-error")).to_contain_text("at least 2")
    expect(search_field).to_have_attribute("aria-describedby", "transaction-search-error")
    page.wait_for_timeout(350)
    assert len(transaction_requests) == before_invalid
    assert "Transactions could not be loaded." not in page.locator("body").inner_text()
    with page.expect_response(lambda response: "/api/v1/transactions?" in response.url and parse_qs(urlparse(response.url).query).get("search") == ["😀😀"] and response.status == 200):
        search_field.fill("😀😀")
    expect(page.get_by_text("No transactions match these filters.")).to_be_visible()
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_role("button", name="Reset filters").click()
    expect(page.locator(".activity-table tbody tr")).to_have_count(13)
    page.set_viewport_size({"width": 375, "height": 812})
    expect(page.locator(".activity-table").first).to_be_visible()
    page.get_by_role("button", name="Hide amounts").click()
    assert "R439.00" not in page.locator("body").inner_text()
    first = page.locator(".activity-link").first
    first.click()
    expect(page.locator(".detail-close")).to_be_focused()
    assert "R439.00" not in page.get_by_role("dialog").inner_text()
    page.keyboard.press("Tab")
    expect(page.locator(".detail-close")).to_be_focused()
    page.keyboard.press("Escape")
    expect(first).to_be_focused()
    page.get_by_role("button", name="Show amounts").click()
    first_amount = page.locator(".activity-table td.amount").first.inner_text().splitlines()[0]
    for width in (320, 375, 390, 430, 599, 600, 601, 767, 768, 769, 820, 839, 840, 841, 1024, 1280, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            overflowing = page.evaluate("""() => [...document.querySelectorAll('*')]
                .filter(el => el.getBoundingClientRect().right > innerWidth)
                .map(el => [el.tagName, el.className, el.getBoundingClientRect().right])
                .slice(0, 20)""")
            raise AssertionError((width, overflowing))
        expect(page.locator(".activity-table").first).to_be_visible()
        amount = page.locator(".activity-table td.amount").first
        assert first_amount in amount.inner_text(), width
        assert page.locator(".activity-table .provisional-note").count() > 0
        assert amount.evaluate("el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && el.scrollWidth <= el.clientWidth + 1 }") , width
        if width < 600:
            assert page.locator(".mobile-nav-anchor").is_visible()
            assert page.evaluate("() => { window.scrollTo(0, document.body.scrollHeight); return document.querySelector('.activity-pagination').getBoundingClientRect().bottom <= innerHeight - 50 }") , width
        if width in (768, 841, 1280):
            page.get_by_role("button", name="Hide amounts").click()
            assert "R439.00" not in page.locator(".activity-surface").inner_text(), width
            page.get_by_role("button", name="Show amounts").click()
        if width in (320, 768, 841):
            page.locator(".activity-link").first.click()
            expect(page.locator(".detail-close")).to_be_focused()
            expect(page.get_by_role("dialog")).to_contain_text(first_amount)
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
    project = os.getenv("CSI_COMPOSE_PROJECT")
    if project:
        def fixture_sql(sql):
            subprocess.run(
                ["docker", "compose", "-p", project, "exec", "-T", "db", "sh", "-c",
                 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U customer_insights -d customer_insights -v ON_ERROR_STOP=1'],
                input=sql, text=True, check=True, capture_output=True,
            )
        fixture_sql("""
            BEGIN;
            INSERT INTO authorizations(id,account_id,authorized_amount_minor,occurred_at,lifecycle_status,raw_description,source_event_id)
            SELECT 'browser-'||n,'f09-everyday',1000,'2026-10-30 12:00+02'::timestamptz+n*interval '1 minute',
                   'PENDING','Browser paging fixture','browser:paging:'||n
            FROM generate_series(1,20) AS n
            ON CONFLICT (id) DO NOTHING;
            UPDATE customers SET customer_revision=customer_revision+1 WHERE id='fixture-f09';
            COMMIT;
        """)
        page.get_by_role("button", name="Refresh data").click()
        next_button = page.locator(".activity-pagination button").last
        expect(next_button).to_be_enabled()
        statuses = []
        page.on("response", lambda response: statuses.append(response.status) if "/api/v1/transactions?" in response.url else None)
        fixture_sql("UPDATE customers SET customer_revision=customer_revision+1 WHERE id='fixture-f09';")
        with page.expect_response(lambda response: "/api/v1/transactions?" in response.url and response.status == 409):
            next_button.click()
        expect(page.locator(".activity-table tbody tr")).to_have_count(25)
        assert statuses.count(409) == 1, statuses
    large = browser.new_page(viewport={"width": 841, "height": 900})
    large.goto(base, wait_until="networkidle")
    large.get_by_label("Login ID").fill("fixture-large")
    large.get_by_label("Password").fill("fixture-only-password")
    large.get_by_role("button", name="Sign in").click()
    navigate(large, "Transactions")
    for width in (320, 768, 840, 841, 1024, 1440):
        large.set_viewport_size({"width": width, "height": 900})
        amount = large.locator(".activity-table td.amount").first
        expect(amount).to_contain_text("R90,071,992,547,409.93")
        assert amount.evaluate("el => { const r = el.getBoundingClientRect(), p = el.closest('.activity-surface').getBoundingClientRect(); return r.left >= p.left && r.right <= p.right && el.scrollWidth <= el.clientWidth + 1 }") , width
        assert not large.evaluate("document.documentElement.scrollWidth > window.innerWidth"), width
    large.close()
    assert not errors, errors
    print("Transaction browser checks passed across 17 widths")
    browser.close()
