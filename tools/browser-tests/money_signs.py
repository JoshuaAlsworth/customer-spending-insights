"""Signed Money out checks against real fixture summaries."""

import os
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


BASE = os.getenv("CSI_BROWSER_BASE_URL", "http://127.0.0.1:8088")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width in (375, 1280):
        for fixture, day, expected in (
            ("fixture-f01", None, "−R850.00"),
            ("fixture-f09", "2026-10-28", "+R120.00"),
            ("fixture-f01", "2026-10-01", "R0.00"),
        ):
            page = browser.new_page(viewport={"width": width, "height": 900})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            response = page.goto(BASE, wait_until="networkidle")
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert (
                "frame-ancestors 'none'" in response.headers["content-security-policy"]
            )
            assert "strict-transport-security" not in response.headers
            page.get_by_label("Login ID").fill(fixture)
            page.get_by_label("Password", exact=True).fill("fixture-only-password")
            page.get_by_role("button", name="Sign in").click()
            if day:
                page.locator(".period-picker summary").click()
                page.get_by_role("button", name="Custom dates").click()
                page.get_by_label("From", exact=True).fill(day)
                page.get_by_label("To", exact=True).fill(day)
                page.get_by_role("button", name="Apply period").click()
            metric = page.locator(".summary-card.primary .metric-value")
            expect(metric).to_have_text(expected)
            if fixture == "fixture-f09":
                expect(
                    page.locator(".summary-card.primary .metric-note")
                ).to_contain_text("Refunds exceeded posted outgoings")
            expect(page.get_by_role("button", name="Hide amounts")).to_have_count(0)
            assert not page.evaluate(
                "document.documentElement.scrollWidth > innerWidth"
            )
            assert not errors, (width, fixture, day, errors)
            page.close()
    for width in (375, 1280):
        for name, amounts, ticks, zero, endpoints in (
            (
                "positive",
                [10000, 5000, 0],
                ["R100", "R75", "R50", "R25", "R0"],
                1,
                [0, 0.5, 1],
            ),
            (
                "negative",
                [-10000, -5000, 0],
                ["R0", "−R25", "−R50", "−R75", "−R100"],
                0,
                [1, 0.5, 0],
            ),
            (
                "mixed",
                [10000, -10000, 0],
                ["R100", "R50", "R0", "−R50", "−R100"],
                0.5,
                [0, 1, 0.5],
            ),
            (
                "zero",
                [0, 0, 0],
                ["R0.04", "R0.03", "R0.02", "R0.01", "R0"],
                1,
                [1, 1, 1],
            ),
        ):
            page = browser.new_page(viewport={"width": width, "height": 900})

            def chart_response(route):
                response = route.fetch()
                data = response.json()
                data["trend"] = [
                    {
                        "from": f"2026-10-0{i + 1}",
                        "to": f"2026-10-0{i + 1}",
                        "netSpendingMinor": str(value),
                    }
                    for i, value in enumerate(amounts)
                ]
                route.fulfill(response=response, body=json.dumps(data))

            page.route("**/api/v1/dashboard*", chart_response)
            page.goto(BASE, wait_until="networkidle")
            page.get_by_label("Login ID").fill("fixture-f01")
            page.get_by_label("Password", exact=True).fill("fixture-only-password")
            page.get_by_role("button", name="Sign in").click()
            expect(page.locator(".trend-axis span")).to_have_text(ticks)
            expect(page.locator(".transfer-note")).to_contain_text("−R2,000.00")
            expect(page.locator(".section-meta")).to_have_text("Period totals")
            page.evaluate(
                "Promise.all(document.getAnimations().map(animation => animation.finished))"
            )
            plot = page.locator(".trend-plot").bounding_box()
            baseline = page.locator(".trend-zero").bounding_box()
            assert abs(baseline["y"] - (plot["y"] + plot["height"] * zero)) < 1
            for i, tick in enumerate(page.locator(".trend-axis span").all()):
                box = tick.bounding_box()
                assert (
                    abs(
                        box["y"]
                        + box["height"] / 2
                        - (plot["y"] + plot["height"] * i / 4)
                    )
                    < 1
                )
            for i, bar in enumerate(page.locator(".trend-bar").all()):
                box = bar.bounding_box()
                endpoint = box["y"] if amounts[i] >= 0 else box["y"] + box["height"]
                assert (
                    abs(endpoint - (plot["y"] + plot["height"] * endpoints[i])) < 1
                ), (name, width, i, box, plot, endpoints[i])
            assert not page.evaluate(
                "document.documentElement.scrollWidth > innerWidth"
            )
            if os.getenv("CSI_SCREENSHOT_DIR"):
                page.screenshot(
                    path=str(
                        Path(os.environ["CSI_SCREENSHOT_DIR"])
                        / f"chart-{name}-{width}.png"
                    ),
                    full_page=True,
                )
            page.close()
    browser.close()

print("Signed Money out, refund-only, zero passed at mobile and desktop widths")
