"""Focused browser journey for local operator simulation and manual refresh."""

import os
import subprocess
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
project = os.environ["CSI_COMPOSE_PROJECT"]
base = os.getenv("CSI_BROWSER_BASE_URL", "http://127.0.0.1:8088")


def operator(*args):
    result = subprocess.run(["./dev", *args], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


subprocess.run(
    ["docker", "compose", "-p", project, "exec", "-T", "db", "sh", "-c",
     'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -v ON_ERROR_STOP=1 -U customer_insights -d customer_insights'],
    cwd=ROOT,
    input="INSERT INTO merchants(id,display_name,mcc,default_category_code) VALUES ('browser-sim-merchant','Browser simulator merchant','5411','GROCERIES');\n",
    text=True, capture_output=True, check=True,
)
os.environ["CSI_ISOLATED_TEST_DB"] = "1"
operator("simulate:provision", project, project, "--fixture")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(base, wait_until="networkidle")
    page.get_by_label("Login ID").fill("fixture-f01")
    page.get_by_label("Password").fill("fixture-only-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator(".summary-card .metric-value")).to_have_count(3)
    page.locator(".account-button").click()
    page.get_by_role("radio", name="All accounts").check()
    expect(page.locator(".summary-card .metric-value")).to_have_count(3)
    before = page.request.get(base + "/api/v1/dashboard").json()
    balances_before = page.request.get(base + "/api/v1/accounts").json()
    expect(page.locator(".account-option").first).to_contain_text("R25,650.00")
    page.locator(".sidebar-nav").get_by_role("button", name="Transactions").click()
    expect(page.locator(".selected-balance")).to_contain_text("R25,650.00")
    old_cursor = page.request.get(base + "/api/v1/transactions?limit=1").json()["nextCursor"]
    assert old_cursor

    operator("simulate", project, project, "pending", "browserpending", "f01-everyday",
             "browser-sim-merchant", "25000", "2026-10-30T10:00:00+02:00", "Browser pending")
    stale = page.request.get(base + "/api/v1/transactions", params={"limit": "1", "cursor": old_cursor})
    assert stale.status == 409 and stale.json()["code"] == "STALE_CURSOR"
    page.get_by_role("button", name="Refresh data").click()
    pending_row = page.locator(".activity-table tbody tr").filter(has_text="Browser simulator merchant")
    expect(pending_row).to_have_count(1)
    expect(page.locator(".activity-section").filter(has_text="Browser simulator merchant")).to_contain_text("Pending transactions")
    pending_row.locator(".activity-link").click()
    expect(page.get_by_role("dialog")).to_contain_text("R250.00")
    page.keyboard.press("Escape")
    pending_summary = page.request.get(base + "/api/v1/dashboard").json()["summary"]
    assert pending_summary == before["summary"]
    assert page.request.get(base + "/api/v1/accounts").json()["combinedPostedBalanceMinor"] == balances_before["combinedPostedBalanceMinor"]
    expect(page.locator(".selected-balance")).to_contain_text("R25,650.00")

    operator("simulate", project, project, "post", "browserpost", "sim_auth_browserpending",
             "24000", "2026-10-30T11:00:00+02:00")
    page.get_by_role("button", name="Refresh data").click()
    posted_row = page.locator(".activity-table tbody tr").filter(has_text="Browser simulator merchant")
    expect(posted_row).to_have_count(1)
    expect(page.locator(".activity-section").filter(has_text="Browser simulator merchant")).to_contain_text("Posted transactions")
    expect(posted_row).to_contain_text("R240.00")
    posted_row.locator(".activity-link").click()
    expect(page.get_by_role("dialog")).to_contain_text("R250.00")
    page.keyboard.press("Escape")
    after = page.request.get(base + "/api/v1/dashboard").json()
    assert int(after["summary"]["netSpendingMinor"]) - int(before["summary"]["netSpendingMinor"]) == 24000
    assert int(after["summary"]["netMovementMinor"]) - int(before["summary"]["netMovementMinor"]) == -24000
    balances_after = page.request.get(base + "/api/v1/accounts").json()
    assert int(balances_after["combinedPostedBalanceMinor"]) - int(balances_before["combinedPostedBalanceMinor"]) == -24000
    expect(page.locator(".selected-balance")).to_contain_text("R25,410.00")
    page.locator(".sidebar-nav").get_by_role("button", name="Overview").click()
    expect(page.locator(".summary-card .metric-value")).to_have_count(3)
    expect(page.locator(".account-option").first).to_contain_text("R25,410.00")

    operator("simulate", project, project, "pending", "browsercancelpending", "f01-everyday",
             "browser-sim-merchant", "4300", "2026-10-30T12:00:00+02:00", "Browser cancel")
    operator("simulate", project, project, "cancel", "browsercancel", "sim_auth_browsercancelpending", "2026-10-30T12:30:00+02:00")
    page.get_by_role("button", name="Refresh data").click()
    page.locator(".sidebar-nav").get_by_role("button", name="Transactions").click()
    page.locator(".transaction-filter-menu summary").click()
    page.get_by_label("Status").select_option("CANCELLED")
    cancelled = page.locator(".activity-table tbody tr").filter(has_text="Browser simulator merchant")
    expect(cancelled).to_have_count(1)
    expect(page.locator(".activity-section").filter(has_text="Browser simulator merchant")).to_contain_text("Cancelled transactions")
    assert page.request.get(base + "/api/v1/dashboard").json()["summary"] == after["summary"]
    assert page.request.get(base + "/api/v1/accounts").json()["combinedPostedBalanceMinor"] == balances_after["combinedPostedBalanceMinor"]
    expect(page.locator(".selected-balance")).to_contain_text("R25,410.00")

    other = browser.new_page(viewport={"width": 1280, "height": 900})
    other.goto(base, wait_until="networkidle")
    other.get_by_label("Login ID").fill("fixture-f03")
    other.get_by_label("Password").fill("fixture-only-password")
    other.get_by_role("button", name="Sign in").click()
    other.locator(".sidebar-nav").get_by_role("button", name="Transactions").click()
    expect(other.locator(".activity-table tbody tr").filter(has_text="Browser simulator merchant")).to_have_count(0)
    assert other.request.get(base + "/api/v1/simulate").status == 403
    other.close()
    browser.close()
print("Simulator browser pending, post, cancel and manual refresh passed")
