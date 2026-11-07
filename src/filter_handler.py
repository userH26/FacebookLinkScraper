"""
Facebook Page Date Filter Handler.
Interacts with the native Facebook Page "Filters" dialog (Year -> Month -> Day)
and provides fallback date parsing and timeline positioning.
"""

import datetime
import logging
import re
import time
from typing import Optional, Tuple

from playwright.sync_api import Page

logger = logging.getLogger("FilterHandler")

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

MONTH_MAP = {
    "jan": (1, "January"), "january": (1, "January"),
    "feb": (2, "February"), "february": (2, "February"),
    "mar": (3, "March"), "march": (3, "March"),
    "apr": (4, "April"), "april": (4, "April"),
    "may": (5, "May"),
    "jun": (6, "June"), "june": (6, "June"),
    "jul": (7, "July"), "july": (7, "July"),
    "aug": (8, "August"), "august": (8, "August"),
    "sep": (9, "September"), "september": (9, "September"),
    "oct": (10, "October"), "october": (10, "October"),
    "nov": (11, "November"), "november": (11, "November"),
    "dec": (12, "December"), "december": (12, "December"),
}


def parse_filter_date_string(date_input: str) -> Tuple[datetime.date, int, str, int]:
    """
    Parses date strings like '2026 September 01', '2026-09-01', '1 September 2026'.

    :param date_input: Raw date string
    :return: (datetime.date, year: int, month_name: str, day: int)
    """
    if not date_input or not isinstance(date_input, str):
        raise ValueError("Invalid date input. Please provide a date string.")

    cleaned = date_input.strip()

    # Format 1: ISO YYYY-MM-DD
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", cleaned):
        dt = datetime.date.fromisoformat(cleaned)
        month_name = MONTH_NAMES[dt.month - 1]
        return dt, dt.year, month_name, dt.day

    # Format 2: "2026 September 01" or "2026 Sep 1"
    m = re.match(r"^(\d{4})\s+([a-zA-Z]+)\s+(\d{1,2})$", cleaned)
    if m:
        year = int(m.group(1))
        m_str = m.group(2).lower()
        day = int(m.group(3))
        for prefix, (m_num, full_name) in MONTH_MAP.items():
            if m_str.startswith(prefix):
                dt = datetime.date(year, m_num, day)
                return dt, year, full_name, day

    # Format 3: "01 September 2026" or "September 01, 2026"
    m = re.match(r"^(?:(\d{1,2})\s+([a-zA-Z]+)|([a-zA-Z]+)\s+(\d{1,2})),?\s*(\d{4})$", cleaned)
    if m:
        day_str = m.group(1) or m.group(4)
        m_str = (m.group(2) or m.group(3)).lower()
        year = int(m.group(5))
        day = int(day_str)
        for prefix, (m_num, full_name) in MONTH_MAP.items():
            if m_str.startswith(prefix):
                dt = datetime.date(year, m_num, day)
                return dt, year, full_name, day

    raise ValueError(
        f"Unable to parse filter date '{date_input}'. "
        f"Supported formats: 'YYYY-MM-DD' (e.g. 2026-09-01) or 'YYYY Month DD' (e.g. 2026 September 01)."
    )


def select_combobox_option(
    page: Page,
    combobox_type: str,
    target_val: str,
    timeout_sec: int = 8,
) -> bool:
    """
    Selects target_val in the given combobox ('year', 'month', 'day') strictly inside the visible Post filters dialog.
    Uses Playwright page.mouse for native human clicks so React state updates reliably.
    """
    start_time = time.time()
    target_clean = str(target_val).strip()

    # Step 1: Click the target combobox inside the visible Post filters dialog
    combo_info = None
    while time.time() - start_time < timeout_sec:
        combo_info = page.evaluate(
            r"""(label) => {
                const dialog = Array.from(document.querySelectorAll('div[role="dialog"]')).find(d => {
                    const r = d.getBoundingClientRect();
                    const text = (d.innerText || '').toLowerCase();
                    return r.width > 200 && (text.includes('post filters') || text.includes('filter') || text.includes('ফিল্টার'));
                });
                if (!dialog) return { success: false, reason: "dialog not found" };

                const combos = Array.from(dialog.querySelectorAll('div[role="combobox"], [aria-haspopup="listbox"]'));
                let target = null;
                if (label.toLowerCase() === 'year') {
                    target = combos[0];
                } else if (label.toLowerCase() === 'month') {
                    target = combos.length > 1 ? combos[1] : combos[0];
                } else if (label.toLowerCase() === 'day') {
                    target = combos.length > 2 ? combos[2] : combos[0];
                }

                if (!target) return { success: false, reason: "target combo not found" };

                target.scrollIntoView({ block: 'center', behavior: 'instant' });
                const r = target.getBoundingClientRect();
                return { success: true, x: r.x + r.width / 2, y: r.y + r.height / 2, text: target.innerText };
            }""",
            combobox_type,
        )
        if combo_info and combo_info.get("success"):
            break
        page.wait_for_timeout(400)

    if not combo_info or not combo_info.get("success"):
        logger.warning("Could not find combobox '%s': %s", combobox_type, combo_info.get("reason") if combo_info else "timeout")
        return False

    page.mouse.click(combo_info["x"], combo_info["y"])
    page.wait_for_timeout(1000)

    # Step 2: Click option in listbox
    opt_info = None
    start_opt_poll = time.time()
    while time.time() - start_opt_poll < 6:
        opt_info = page.evaluate(
            r"""(val) => {
                const listbox = Array.from(document.querySelectorAll('div[role="listbox"], div[role="menu"]')).find(lb => {
                    const r = lb.getBoundingClientRect();
                    return r.width > 50 && r.height > 50;
                });
                if (!listbox) return { success: false, reason: "listbox not found" };

                const options = Array.from(listbox.querySelectorAll('div[role="option"], div[role="menuitemradio"], div[role="button"], span'));
                const targetOpt = options.find(o => {
                    const t = (o.innerText || '').trim().toLowerCase();
                    const v = String(val).trim().toLowerCase();
                    return t === v || (parseInt(t) === parseInt(v) && !isNaN(parseInt(t)) && !isNaN(parseInt(v)));
                });

                if (!targetOpt) {
                    return { success: false, reason: "option not found" };
                }

                targetOpt.scrollIntoView({ block: 'center', behavior: 'instant' });
                const r = targetOpt.getBoundingClientRect();
                return { success: true, x: r.x + r.width / 2, y: r.y + r.height / 2, text: targetOpt.innerText };
            }""",
            target_clean,
        )
        if opt_info and opt_info.get("success"):
            break
        page.wait_for_timeout(400)

    if not opt_info or not opt_info.get("success"):
        logger.warning("Could not select option '%s' for combobox '%s'", target_clean, combobox_type)
        return False

    page.mouse.click(opt_info["x"], opt_info["y"])
    page.wait_for_timeout(1200)
    return True


def apply_page_date_filter(
    page: Page,
    year: int,
    month_name: str,
    day: int,
) -> bool:
    """
    Clicks Facebook's Posts 'Filters' button and handles the sequential
    Year -> Month -> Day dropdown selections.

    :param page: Active Playwright Page on the Facebook Page
    :param year: Target year (e.g. 2026)
    :param month_name: Target month full name (e.g. 'September')
    :param day: Target day of month (e.g. 1)
    :return: True if the filter was successfully selected and applied, False otherwise
    """
    logger.info("Navigating to target date via Facebook filter: %d %s %02d", year, month_name, day)
    target_page_url = page.url.split("?")[0]

    try:
        # Step 1: Locate and click the Posts 'Filters' button
        btn_info = None
        for attempt in range(12):
            btn_info = page.evaluate(r"""() => {
                let btn = document.querySelector('div[role="button"][aria-label="Filters" i]') ||
                          document.querySelector('div[role="button"][aria-label="Filter" i]') ||
                          document.querySelector('div[role="button"][aria-label*="ফিল্টার"]') ||
                          Array.from(document.querySelectorAll('div[role="button"], span[role="button"]')).find(b => {
                              const t = (b.innerText || '').trim().toLowerCase();
                              const a = (b.getAttribute('aria-label') || '').trim().toLowerCase();
                              return t === 'filters' || t === 'filter' || t.includes('ফিল্টার') ||
                                     a === 'filters' || a === 'filter' || a.includes('ফিল্টার');
                          });
                if (!btn) {
                    // Fallback: search for leaf elements with text "Filters"
                    const el = Array.from(document.querySelectorAll('span, div, button')).find(e => {
                        const t = (e.innerText || '').trim().toLowerCase();
                        return (t === 'filters' || t === 'filter' || t === 'ফিল্টার') && e.children.length === 0;
                    });
                    if (el) {
                        btn = el.closest('div[role="button"], span[role="button"], div[tabindex="0"], button') || el;
                    }
                }
                if (!btn) return null;
                btn.scrollIntoView({ block: 'center', behavior: 'instant' });
                const r = btn.getBoundingClientRect();
                return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
            }""")
            if btn_info:
                break
            page.mouse.wheel(0, 350)
            page.wait_for_timeout(1000)

        if not btn_info:
            logger.error("Could not find Posts 'Filters' button on page after 12 attempts.")
            return False

        logger.info("Found Filters button. Clicking...")
        page.mouse.click(btn_info["x"], btn_info["y"])
        page.wait_for_timeout(2000)

        # Step 2: Select Year
        logger.info("Selecting Year: %s", year)
        if not select_combobox_option(page, "year", str(year)):
            return False

        # Step 3: Select Month
        logger.info("Selecting Month: %s", month_name)
        if not select_combobox_option(page, "month", month_name):
            return False

        # Step 4: Select Day
        logger.info("Selecting Day: %s", day)
        if not select_combobox_option(page, "day", str(day)):
            return False

        # Step 5: Click "Done" button in dialog
        done_res = page.evaluate(r"""() => {
            const dialog = Array.from(document.querySelectorAll('div[role="dialog"]')).find(d => {
                const r = d.getBoundingClientRect();
                const text = (d.innerText || '').toLowerCase();
                return r.width > 200 && (text.includes('post filters') || text.includes('filter') || text.includes('ফিল্টার'));
            });
            if (!dialog) return { success: false };

            const buttons = Array.from(dialog.querySelectorAll('div[role="button"]'));
            const done = buttons.find(b => {
                const t = (b.innerText || '').trim().toLowerCase();
                const a = (b.getAttribute('aria-label') || '').trim().toLowerCase();
                return t === 'done' || t === 'apply' || t.includes('সম্পন্ন') ||
                       a === 'done' || a === 'apply' || a.includes('সম্পন্ন');
            });
            if (!done) return { success: false };

            const r = done.getBoundingClientRect();
            return { success: true, x: r.x + r.width / 2, y: r.y + r.height / 2 };
        }""")

        if not done_res or not done_res.get("success"):
            logger.warning("Could not find 'Done' button in Post filters dialog.")
            return False

        logger.info("Clicking 'Done' in Filter dialog. Waiting for feed to jump to date...")
        page.mouse.click(done_res["x"], done_res["y"])
        page.wait_for_timeout(4000)

        # Ensure we did not navigate away
        if not page.url.startswith(target_page_url):
            logger.warning("Detected navigation away from page URL. Restoring: %s", target_page_url)
            page.goto(target_page_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

        logger.info("Successfully positioned feed at target date: %d %s %02d", year, month_name, day)
        return True

    except Exception as e:
        logger.error("Error during Page Date Filter interaction: %s", e)
        return False
