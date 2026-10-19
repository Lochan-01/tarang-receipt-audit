import os
import time
import threading
import pytest
from pathlib import Path
import requests
import uvicorn
from playwright.sync_api import sync_playwright

from tarang.service.app import app

SAMPLE_IMAGE = Path("sample_receipt_fuel.jpg").resolve()

@pytest.fixture(scope="module")
def live_server_url():
    """Provides a live running server URL for UI tests."""
    # Check if existing server is running
    try:
        r = requests.get("http://127.0.0.1:8000/health", timeout=1)
        if r.status_code == 200:
            yield "http://127.0.0.1:8000"
            return
    except Exception:
        pass

    # Start test server on port 8008
    config = uvicorn.Config(app, host="127.0.0.1", port=8008, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = "http://127.0.0.1:8008"
    for _ in range(40):
        try:
            r = requests.get(f"{url}/health", timeout=0.5)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.2)

    yield url
    server.should_exit = True

def test_claim_form_ui_lifecycle(live_server_url):
    """
    Playwright UI Test verifying the required claim form behaviour:
    1. On page load: claim fields and submit button are hidden.
    2. After selecting an image: preview is shown, claim fields are revealed.
    3. Revealed claim fields are strictly empty with expected placeholders.
    4. Submit button stays disabled until all 5 fields are filled.
    5. When user removes or cancels image: fields are re-hidden and form resets.
    """
    assert SAMPLE_IMAGE.exists(), f"Sample image {SAMPLE_IMAGE} must exist"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Page load
        page.goto(live_server_url)

        # Receipt photo input and preview box must be visible
        assert page.locator("#receiptFile").is_visible(), "Receipt photo file chooser must be visible on load"
        assert page.locator("#imgPreview").is_visible(), "Image preview box must be visible on load"

        # Claim fields and submit button must be hidden on load
        claim_section = page.locator("#claimFieldsSection")
        assert not claim_section.is_visible(), "Claim fields section must be hidden on page load"
        assert not page.locator("#btnSubmit").is_visible(), "Submit button must be hidden on page load"

        # 2. Select receipt image
        page.set_input_files("#receiptFile", str(SAMPLE_IMAGE))

        # Preview box must now contain an image
        page.wait_for_selector("#imgPreview img")
        assert page.locator("#imgPreview img").is_visible(), "Receipt preview image must be visible after upload"

        # Claim fields section must now be revealed
        assert claim_section.is_visible(), "Claim fields section must be revealed after image selection"
        assert page.locator("#btnSubmit").is_visible(), "Submit button must be revealed after image selection"

        # 3. All claim fields must be EMPTY when revealed
        emp_val = page.locator("#empId").input_value()
        cat_val = page.locator("#category").input_value()
        amt_val = page.locator("#claimedAmt").input_value()
        date_val = page.locator("#expenseDate").input_value()
        vendor_val = page.locator("#vendorHint").input_value()

        assert emp_val == "", f"Employee select must be empty/unselected, got: '{emp_val}'"
        assert cat_val == "", f"Category select must be empty/unselected, got: '{cat_val}'"
        assert amt_val == "", f"Claimed amount must be empty, got: '{amt_val}'"
        assert date_val == "", f"Expense date must be empty, got: '{date_val}'"
        assert vendor_val == "", f"Vendor hint must be empty, got: '{vendor_val}'"

        # Check placeholders
        assert page.locator("#claimedAmt").get_attribute("placeholder") == "Enter amount in Rs"
        assert page.locator("#expenseDate").get_attribute("placeholder") == "YYYY-MM-DD"
        assert page.locator("#vendorHint").get_attribute("placeholder") == "Vendor name as entered by rep"

        # 4. Submit button must stay DISABLED until all fields are filled
        submit_btn = page.locator("#btnSubmit")
        assert submit_btn.is_disabled(), "Submit button must be disabled when fields are empty"

        # Fill fields one by one and verify submit stays disabled until the final field
        page.select_option("#empId", "TPD-0412")
        assert submit_btn.is_disabled(), "Submit button must be disabled after filling only employee"

        page.select_option("#category", "Fuel")
        assert submit_btn.is_disabled(), "Submit button must be disabled after filling category"

        page.fill("#claimedAmt", "250.00")
        assert submit_btn.is_disabled(), "Submit button must be disabled after filling amount"

        page.fill("#expenseDate", "2026-06-10")
        assert submit_btn.is_disabled(), "Submit button must be disabled after filling date"

        # Fill the 5th and final field
        page.fill("#vendorHint", "Laxmi Auto Fuels")

        # Now submit button must be ENABLED
        assert submit_btn.is_enabled(), "Submit button must become enabled once all 5 fields are filled"

        # 5. Clear image / remove image -> fields must be re-hidden and form reset
        page.set_input_files("#receiptFile", [])
        assert not claim_section.is_visible(), "Claim fields section must be re-hidden when image is removed"
        assert submit_btn.is_disabled(), "Submit button must be disabled when image is removed"

        browser.close()
