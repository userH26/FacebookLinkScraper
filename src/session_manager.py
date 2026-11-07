"""
Session and cookie management for Facebook scraper.
Supports importing cookies from JSON files (Cookie-Editor, EditThisCookie, Playwright storage state),
Netscape cookies.txt, raw c_user/xs cookies, and interactive browser login.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from playwright.sync_api import BrowserContext

logger = logging.getLogger("SessionManager")


def normalize_cookie_for_playwright(cookie: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalizes a cookie dictionary to conform to Playwright's add_cookies schema.
    """
    if not isinstance(cookie, dict):
        return None

    name = cookie.get("name")
    value = cookie.get("value")
    if not name or value is None:
        return None

    domain = cookie.get("domain", ".facebook.com")
    path = cookie.get("path", "/")

    # Ensure domain matches facebook
    if "facebook.com" not in domain:
        domain = ".facebook.com"

    # Playwright requires sameSite to be 'Strict', 'Lax', or 'None'
    raw_samesite = str(cookie.get("sameSite", "")).lower().strip()
    same_site = "Lax"
    if "none" in raw_samesite or "no_restriction" in raw_samesite:
        same_site = "None"
    elif "strict" in raw_samesite:
        same_site = "Strict"
    elif "lax" in raw_samesite:
        same_site = "Lax"

    clean_cookie = {
        "name": str(name),
        "value": str(value),
        "domain": domain,
        "path": path,
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": bool(cookie.get("secure", True)),
        "sameSite": same_site,
    }

    # Optional expiration
    expires = cookie.get("expirationDate") or cookie.get("expires")
    if isinstance(expires, (int, float)) and expires > 0:
        clean_cookie["expires"] = float(expires)

    return clean_cookie


def parse_netscape_cookies(content: str) -> List[Dict[str, Any]]:
    """Parses standard tab-separated Netscape / cookies.txt file content."""
    cookies = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            domain, flag, path, secure, expiration, name, value = parts[:7]
            cookies.append({
                "domain": domain,
                "path": path,
                "secure": secure.lower() == "true",
                "expires": float(expiration) if expiration.isdigit() else -1,
                "name": name,
                "value": value,
            })
    return cookies


def import_cookies_from_file(context: BrowserContext, file_path: str) -> int:
    """
    Imports cookies from a JSON file (Cookie-Editor / Playwright storage_state)
    or cookies.txt file into the active BrowserContext.

    :param context: Active Playwright BrowserContext
    :param file_path: Path to the cookie file
    :return: Number of cookies imported successfully
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Cookie file not found: {file_path}")

    logger.info("Importing cookies from: %s", file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    raw_cookies: List[Dict[str, Any]] = []

    # Try parsing as JSON first
    if content.startswith("[") or content.startswith("{"):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                raw_cookies = parsed
            elif isinstance(parsed, dict) and "cookies" in parsed:
                raw_cookies = parsed["cookies"]
        except json.JSONDecodeError as e:
            logger.warning("JSON decode failed, attempting Netscape text parse: %s", e)
            raw_cookies = parse_netscape_cookies(content)
    else:
        raw_cookies = parse_netscape_cookies(content)

    normalized_cookies: List[Dict[str, Any]] = []
    for c in raw_cookies:
        norm = normalize_cookie_for_playwright(c)
        if norm:
            normalized_cookies.append(norm)

    if not normalized_cookies:
        logger.warning("No valid cookies found in %s", file_path)
        return 0

    try:
        context.add_cookies(normalized_cookies)
        logger.info("Successfully imported %d cookies into browser session.", len(normalized_cookies))
        return len(normalized_cookies)
    except Exception as e:
        logger.error("Error adding cookies to context: %s", e)
        # Attempt adding one-by-one to isolate failures
        success_count = 0
        for nc in normalized_cookies:
            try:
                context.add_cookies([nc])
                success_count += 1
            except Exception:
                pass
        logger.info("Imported %d / %d cookies individually.", success_count, len(normalized_cookies))
        return success_count


def import_cuser_xs(
    context: BrowserContext,
    c_user: str,
    xs: str,
    domain: str = ".facebook.com",
) -> None:
    """
    Directly injects the primary Facebook session cookies (c_user and xs).
    """
    cookies = [
        {
            "name": "c_user",
            "value": str(c_user).strip(),
            "domain": domain,
            "path": "/",
            "secure": True,
            "sameSite": "None",
        },
        {
            "name": "xs",
            "value": str(xs).strip(),
            "domain": domain,
            "path": "/",
            "secure": True,
            "sameSite": "None",
        },
    ]
    context.add_cookies(cookies)
    logger.info("Injected c_user and xs authentication cookies for %s", domain)


def interactive_login(context: BrowserContext, session_dir: Optional[str] = None):
    """
    Opens Facebook login page in the browser and waits for the user to complete login.
    """
    page = context.new_page()
    try:
        logger.info("Opening Facebook in browser for interactive login...")
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded")

        print("\n" + "=" * 65)
        print("ACTION REQUIRED - FACEBOOK LOGIN:")
        print("1. Log in to your Facebook account in the browser window.")
        print("2. Once your home feed or profile is visible,")
        input("   press ENTER here in your terminal to save session... ")
        print("=" * 65 + "\n")

        if session_dir:
            logger.info("Persistent session saved to: %s", session_dir)
    finally:
        page.close()
