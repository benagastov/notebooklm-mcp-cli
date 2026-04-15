"""Headless authentication for NotebookLM CLI.

This module provides headless login functionality for environments without
a display (e.g., servers, CI/CD pipelines). It supports:
1. Email/password authentication via headless browser automation
2. Environment variable injection for cookies/tokens
3. Cookie file import for pre-authenticated sessions
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from notebooklm_tools.core.exceptions import AuthenticationError
from notebooklm_tools.utils.config import get_base_url, get_chrome_profile_dir

logger = logging.getLogger(__name__)

NOTEBOOKLM_URL = get_base_url()
GOOGLE_ACCOUNTS_URL = "https://accounts.google.com"


def _get_playwright_available() -> bool:
    """Check if Playwright is available for headless automation."""
    try:
        from playwright.sync_api import sync_playwright

        return True
    except ImportError:
        return False


def _check_chromium_installation() -> bool:
    """Check if Chromium is available for Playwright."""
    try:
        result = subprocess.run(
            ["playwright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return "chromium" in result.stdout.lower() or result.returncode == 0
    except Exception:
        return False


def _ensure_playwright_chromium() -> bool:
    """Install Playwright Chromium browser if not available."""
    try:
        logger.info("Installing Playwright Chromium for headless authentication...")
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Failed to install Playwright Chromium: {e}")
        return False


def validate_headless_auth_available() -> tuple[bool, str]:
    """
    Check if headless authentication is available.

    Returns:
        Tuple of (is_available, message)
    """
    # Check Playwright availability
    if not _get_playwright_available():
        return False, "Playwright is not installed"

    # Check Chromium
    if not _check_chromium_installation():
        if not _ensure_playwright_chromium():
            return False, "Failed to install Chromium browser"

    return True, "Ready for headless authentication"


def authenticate_with_playwright(
    email: str,
    password: str,
    profile_name: str = "default",
    timeout: int = 120,
    headless: bool = True,
) -> dict[str, Any]:
    """
    Authenticate with Google using Playwright headless browser.

    This function automates the Google login flow:
    1. Launch headless Chromium
    2. Navigate to Google sign-in
    3. Enter email and password
    4. Handle 2FA if enabled
    5. Extract cookies after successful login

    Args:
        email: Google account email
        password: Google account password
        profile_name: NLM profile name for storing cookies
        timeout: Maximum time to wait for login (seconds)
        headless: Whether to run browser in headless mode

    Returns:
        Dict with cookies, csrf_token, session_id, and email

    Raises:
        AuthenticationError: If login fails
    """
    if not _get_playwright_available():
        raise AuthenticationError(
            message="Playwright is not installed",
            hint="Install it with: pip install playwright && playwright install chromium",
        )

    # Check and install Chromium if needed
    if not _check_chromium_installation():
        if not _ensure_playwright_chromium():
            raise AuthenticationError(
                message="Failed to install Chromium browser",
                hint="Install Chromium manually or use cookie file import instead.",
            )

    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    cookies = []
    extracted_email = email
    csrf_token = ""
    session_id = ""
    build_label = ""

    try:
        with sync_playwright() as p:
            # Launch browser with appropriate settings
            browser_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-popup-blocking",
                "--disable-infobars",
            ]

            browser = p.chromium.launch(
                headless=headless,
                args=browser_args,
            )

            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            page = context.new_page()

            # Navigate to Google sign-in page
            logger.info("Navigating to Google sign-in page...")

            # Try multiple URL patterns for Google sign-in
            signin_urls = [
                "https://accounts.google.com/v3/signin/identifier?continue=https://notebooklm.google.com",
                "https://accounts.google.com/v3/signin/identifier",
                "https://accounts.google.com/signin/v2/identifier?continue=https://notebooklm.google.com",
            ]

            signin_url = None
            for url in signin_urls:
                try:
                    response = page.goto(url, timeout=15000)
                    if response and response.ok:
                        signin_url = url
                        break
                except Exception:
                    continue

            if not signin_url:
                # Fallback to direct URL
                page.goto(signin_urls[0], timeout=30000)

            logger.info(f"Loaded: {page.url}")

            # Wait for page to stabilize
            page.wait_for_load_state("domcontentloaded", timeout=15000)

            # Wait for any email input field - Google uses various selectors
            logger.info("Waiting for email input field...")

            # Try multiple selector patterns
            email_selectors = [
                'input[type="email"]',
                'input[type="text"]',
                'input[name="identifier"]',
                '#identifierId',
                'input[autocomplete="username"]',
            ]

            email_input = None
            for selector in email_selectors:
                try:
                    email_input = page.wait_for_selector(selector, timeout=5000)
                    if email_input:
                        logger.info(f"Found email input with selector: {selector}")
                        break
                except PlaywrightTimeout:
                    continue

            if not email_input:
                # Check if page has alternative structure (CAPTCHA, etc.)
                page_content = page.content()
                if "captcha" in page_content.lower() or "unusual traffic" in page_content.lower():
                    raise AuthenticationError(
                        message="Google detected automated traffic (CAPTCHA required)",
                        hint="Use cookie file import or browser-based login instead.",
                    )
                raise AuthenticationError(
                    message="Could not find email input field on Google sign-in page",
                    hint="Google's sign-in page may have changed. Try cookie file import.",
                )

            # Enter email
            logger.info(f"Entering email: {email}")
            email_input.fill(email)

            # Find and click next button
            next_selectors = [
                'button[id="identifierNext"]',
                'button[type="submit"]',
                'div[data-type="submit"] button',
                '#identifierNext',
                'span:has-text("Next")',
                'button:has-text("Next")',
            ]

            next_button = None
            for selector in next_selectors:
                try:
                    next_button = page.wait_for_selector(selector, timeout=3000)
                    if next_button:
                        break
                except PlaywrightTimeout:
                    continue

            if next_button:
                next_button.click()
            else:
                # Try pressing Enter
                email_input.press("Enter")

            # Wait for password field (or error)
            time.sleep(1)  # Brief pause for page transition

            # Wait for password input
            logger.info("Waiting for password field...")
            password_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[autocomplete="current-password"]',
            ]

            password_input = None
            for selector in password_selectors:
                try:
                    password_input = page.wait_for_selector(selector, timeout=15000)
                    if password_input:
                        logger.info(f"Found password input with selector: {selector}")
                        break
                except PlaywrightTimeout:
                    continue

            if not password_input:
                # Check for error message
                error_elem = page.query_selector('.o6cuMc, .OyEIQ, [aria-live="polite"]')
                if error_elem:
                    error_text = error_elem.inner_text()
                    raise AuthenticationError(
                        message=f"Login failed: {error_text}",
                        hint="Check your email address and try again.",
                    )
                raise AuthenticationError(
                    message="Login flow did not reach password page",
                    hint="Check your email address and try again.",
                )

            # Enter password
            logger.info("Email accepted, entering password...")
            password_input.fill(password)

            # Find and click password submit button
            password_next_selectors = [
                'button[id="passwordNext"]',
                'button[type="submit"]',
                '#passwordNext',
                'span:has-text("Next")',
                'button:has-text("Next")',
            ]

            password_button = None
            for selector in password_next_selectors:
                try:
                    password_button = page.wait_for_selector(selector, timeout=3000)
                    if password_button:
                        break
                except PlaywrightTimeout:
                    continue

            if password_button:
                password_button.click()
            else:
                # Try pressing Enter
                password_input.press("Enter")

            # Wait for either success or 2FA prompt
            login_timeout = time.time() + timeout
            login_successful = False

            while time.time() < login_timeout:
                # Check if redirected to NotebookLM (success)
                current_url = page.url
                if "notebooklm.google.com" in current_url or "notebooklm." in current_url:
                    logger.info("Login successful - redirected to NotebookLM")
                    login_successful = True
                    break

                # Check for 2FA
                if page.query_selector('input[name="totpCode"]'):
                    raise AuthenticationError(
                        message="Two-factor authentication required",
                        hint="Use cookie file import or browser-based login for accounts with 2FA.",
                    )

                # Check for phone verification
                if page.query_selector('[data-challenge="phone"]'):
                    raise AuthenticationError(
                        message="Phone verification required",
                        hint="Use cookie file import or browser-based login for accounts with phone verification.",
                    )

                # Check for password error
                error_elem = page.query_selector('.o6cuMc, .OyEIQ, [aria-live="polite"]')
                if error_elem:
                    error_text = error_elem.inner_text()
                    if "wrong password" in error_text.lower() or "incorrect password" in error_text.lower():
                        raise AuthenticationError(
                            message="Incorrect password",
                            hint="Check your password and try again.",
                        )

                time.sleep(0.5)

            if not login_successful:
                raise AuthenticationError(
                    message="Login timeout - could not complete authentication",
                    hint="Try using cookie file import instead.",
                )

            # Extract cookies
            logger.info("Extracting cookies...")
            cookies = context.cookies()

            # Navigate to NotebookLM to get additional tokens
            logger.info("Navigating to NotebookLM for token extraction...")
            page.goto(NOTEBOOKLM_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=20000)

            # Get page HTML for CSRF token and other values
            html = page.content()

            # Extract CSRF token
            csrf_match = re.search(r'"SNlM0e":"([^"]+)"', html)
            if csrf_match:
                csrf_token = csrf_match.group(1)

            # Extract session ID
            session_match = re.search(r'"FdrFJe":"(\d+)"', html)
            if session_match:
                session_id = session_match.group(1)

            # Extract build label
            build_match = re.search(r'"cfb2h":"([^"]+)"', html)
            if build_match:
                build_label = build_match.group(1)

            browser.close()

    except AuthenticationError:
        raise
    except Exception as e:
        logger.error(f"Playwright authentication failed: {e}")
        raise AuthenticationError(
            message=f"Headless authentication failed: {e}",
            hint="Try using cookie file import or browser-based login instead.",
        )

    if not cookies:
        raise AuthenticationError(
            message="No cookies extracted after login",
            hint="Try using cookie file import instead.",
        )

    # Convert cookies to required format
    cookie_dict = {c["name"]: c["value"] for c in cookies}

    return {
        "cookies": cookies,  # Full list format for saving
        "cookie_dict": cookie_dict,  # Dict format for validation
        "csrf_token": csrf_token,
        "session_id": session_id,
        "email": extracted_email,
        "build_label": build_label,
    }


def authenticate_with_credentials(
    email: str,
    password: str,
    profile_name: str = "default",
    timeout: int = 120,
) -> dict[str, Any]:
    """
    Authenticate with email/password in headless mode.

    This is the main entry point for headless authentication.
    It uses Playwright to automate the Google login flow.

    Args:
        email: Google account email
        password: Google account password
        profile_name: NLM profile name
        timeout: Maximum time to wait for login

    Returns:
        Authentication result dict
    """
    return authenticate_with_playwright(
        email=email,
        password=password,
        profile_name=profile_name,
        timeout=timeout,
        headless=True,
    )


def load_auth_from_environment(profile_name: str = "default") -> dict[str, Any] | None:
    """
    Load authentication from environment variables.

    Supports:
    - NLM_COOKIES: JSON-encoded cookie dict
    - NLM_COOKIE_FILE: Path to cookie file
    - NLM_EMAIL: Google account email (requires NLM_PASSWORD)
    - NLM_PASSWORD: Google account password

    Args:
        profile_name: Profile name for reference

    Returns:
        Auth dict if environment variables are set, None otherwise
    """
    # Check for JSON cookies
    cookies_json = os.environ.get("NLM_COOKIES")
    if cookies_json:
        try:
            cookies = json.loads(cookies_json)
            if isinstance(cookies, dict):
                cookie_list = [{"name": k, "value": v} for k, v in cookies.items()]
            else:
                cookie_list = cookies
            return {
                "cookies": cookie_list,
                "csrf_token": os.environ.get("NLM_CSRF_TOKEN", ""),
                "session_id": os.environ.get("NLM_SESSION_ID", ""),
                "email": os.environ.get("NLM_EMAIL", ""),
                "build_label": os.environ.get("NLM_BUILD_LABEL", ""),
            }
        except json.JSONDecodeError:
            logger.warning("Invalid NLM_COOKIES JSON, ignoring...")

    # Check for cookie file path
    cookie_file = os.environ.get("NLM_COOKIE_FILE")
    if cookie_file:
        from notebooklm_tools.utils.browser import parse_cookies_from_file

        try:
            cookie_dict = parse_cookies_from_file(cookie_file)
            cookie_list = [{"name": k, "value": v} for k, v in cookie_dict.items()]
            return {
                "cookies": cookie_list,
                "csrf_token": os.environ.get("NLM_CSRF_TOKEN", ""),
                "session_id": os.environ.get("NLM_SESSION_ID", ""),
                "email": os.environ.get("NLM_EMAIL", ""),
                "build_label": os.environ.get("NLM_BUILD_LABEL", ""),
            }
        except Exception as e:
            logger.warning(f"Failed to load cookies from file: {e}")

    # Check for email/password
    email = os.environ.get("NLM_EMAIL")
    password = os.environ.get("NLM_PASSWORD")
    if email and password:
        return authenticate_with_credentials(
            email=email,
            password=password,
            profile_name=profile_name,
        )

    return None


# Required cookies for NotebookLM authentication
REQUIRED_COOKIES = ["SID", "HSID", "SSID", "APISID", "SAPISID"]


def validate_cookies(cookies: dict[str, str]) -> bool:
    """Check if required Google auth cookies are present."""
    found = sum(1 for pattern in REQUIRED_COOKIES if any(pattern in name for name in cookies))
    return found >= 2
