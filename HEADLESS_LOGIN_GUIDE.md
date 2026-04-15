# NotebookLM CLI - Headless Login Guide

This document explains how to use the NotebookLM CLI (`nlm`) with headless authentication in server/CI environments without a display.

## Installation

```bash
# Clone the repository
git clone https://github.com/jacob-bd/notebooklm-mcp-cli.git
cd notebooklm-mcp-cli

# Install with headless dependencies (uv recommended)
uv tool install -e ".[headless]"

# Or install with pip
pip install -e ".[headless]"

# Install Playwright Chromium browser
playwright install chromium
```

## Headless Authentication Methods

### Method 1: Environment Variables (Recommended for CI/CD)

```bash
# Set credentials via environment variables
export NLM_EMAIL="your-email@gmail.com"
export NLM_PASSWORD="your-password"

# Login
nlm login --headless --from-env
```

### Method 2: Direct Credentials

```bash
nlm login --headless --email "your-email@gmail.com" --password "your-password"
```

### Method 3: Pre-authenticated Cookies

```bash
# Export cookies from your browser as JSON
export NLM_COOKIES='{"SID": "...", "HSID": "...", ...}'

# Or use cookie file
export NLM_COOKIE_FILE="/path/to/cookies.txt"

nlm login --headless --from-env
```

## Quick Reference

| Scenario | Command |
|----------|---------|
| Headless login with email/password | `nlm login --headless --email user@gmail.com --password secret` |
| Login from environment variables | `nlm login --headless --from-env` |
| Use pre-existing cookies | `nlm login --headless --from-env` (with NLM_COOKIES set) |
| Check current auth status | `nlm login --check` |
| Manual cookie file import | `nlm login --manual --file cookies.txt` |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `NLM_EMAIL` | Google account email |
| `NLM_PASSWORD` | Google account password |
| `NLM_COOKIES` | JSON-encoded cookie dictionary |
| `NLM_COOKIE_FILE` | Path to cookie file |
| `NLM_CSRF_TOKEN` | Optional CSRF token |
| `NLM_SESSION_ID` | Optional session ID |
| `NLM_BUILD_LABEL` | Optional build label (cfb2h key) |

## Notes

- Headless authentication uses Playwright with Chromium in headless mode
- Accounts with 2FA or phone verification may require cookie file import instead
- Cookies are stored in `~/.notebooklm-mcp-cli/profiles/<profile>/`
- Run `nlm doctor` to diagnose authentication issues

## Troubleshooting

### "Playwright is not installed"
```bash
pip install playwright && playwright install chromium
```

### "Could not find email input field"
Google's sign-in page structure may have changed. Try cookie file import:
```bash
nlm login --manual --file cookies.txt
```

### "Google detected automated traffic"
Google may block headless browsers. Use cookie file import or browser-based login.

## Project Status

This project has been modified to support headless login with better error handling and updated Google sign-in selectors.