"""Smoke-test a deployed copy of the app in a headless browser.

    python scripts/smoke_test.py https://<your-app>.streamlit.app [out_dir]

Loads the app (waking it if Streamlit Cloud put it to sleep), searches RIL, checks Dashboard 1
and Dashboard 2, builds and downloads the Excel workbook, and saves screenshots. Exits 1 on any
failure. Run by the Smoke test workflow against the URL in deploy/url.txt.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import Frame, Page, sync_playwright

SEARCH = "input[aria-label='Search a Nifty 100 stock']"


def app_frame(page: Page, timeout_s: int = 240) -> Frame:
    """Streamlit Cloud serves the app inside an iframe and may show a 'wake up' page first."""
    for _ in range(timeout_s):
        for button in ("Yes, get this app back up!", "Wake up"):
            loc = page.get_by_role("button", name=button)
            if loc.count():
                loc.first.click()
        for frame in page.frames:
            if frame.locator(SEARCH).count():
                return frame
        page.wait_for_timeout(1000)
    raise TimeoutError("the app's search box never appeared")


def main(url: str, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    checks: list[tuple[str, bool, str]] = []
    with sync_playwright() as p:
        # CHROMIUM_PATH: use an already-installed browser instead of Playwright's own.
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        page = browser.new_page(viewport={"width": 1400, "height": 1100}, accept_downloads=True)
        page.goto(url, timeout=120_000)
        app = app_frame(page)
        app.fill(SEARCH, "RIL")
        app.press(SEARCH, "Enter")
        app.wait_for_selector("text=Why this trend?", timeout=180_000)
        captions = " | ".join(app.locator("[data-testid=stCaptionContainer]").all_inner_texts())
        source = next((c for c in captions.split(" | ") if c.startswith("Prices:")), "")
        checks.append(("Dashboard 1 loads Reliance", True, source))
        checks.append(("Live Yahoo prices", "Yahoo Finance (live)" in source, source))
        headlines = app.locator("text=Recent headlines").first.inner_text()
        checks.append(("Headlines", "(0)" not in headlines, headlines))
        page.screenshot(path=str(out / "market_now.png"), full_page=True)

        app.get_by_role("tab", name="BMM path trace").click()
        app.wait_for_selector("text=Most recent window", timeout=180_000)
        checks.append(("Dashboard 2 + backtest", True, ""))
        page.screenshot(path=str(out / "path_trace.png"), full_page=True)

        build = app.get_by_role("button", name="Build Excel workbook")
        build.scroll_into_view_if_needed()
        build.click()
        download = app.get_by_role("button", name="Download .xlsx")
        download.wait_for(timeout=180_000)
        with page.expect_download(timeout=120_000) as d:
            download.click()
        d.value.save_as(out / d.value.suggested_filename)
        size = (out / d.value.suggested_filename).stat().st_size
        checks.append(("Excel download", size > 100_000, f"{d.value.suggested_filename}, "
                                                          f"{size / 1e6:.1f} MB"))
        errors = app.locator("[data-testid=stException]").count()
        checks.append(("No app exceptions", errors == 0, f"{errors} exception(s)"))
        browser.close()

    report = [f"# Smoke test: {url}", ""]
    report += [f"- {'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else "")
               for name, ok, detail in checks]
    text = "\n".join(report)
    print(text)
    (out / "report.md").write_text(text + "\n")
    # Live prices and headlines depend on Yahoo / Google from the host's IP: report, don't fail.
    hard = [c for c in checks if c[0] not in ("Live Yahoo prices", "Headlines")]
    return 0 if all(ok for _, ok, _ in hard) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], Path(sys.argv[2] if len(sys.argv) > 2 else "smoke")))
