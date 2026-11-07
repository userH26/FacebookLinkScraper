"""
Date and relative time parsing for Facebook posts.
"""

import datetime
import re
from typing import Optional, Tuple

BENGALI_DIGITS = "০১২৩৪৫৬৭৮৯"
MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def normalize_bengali_digits(text: str) -> str:
    """Replaces Bengali numerals with standard ASCII digits."""
    if not text:
        return ""
    for i, d in enumerate(BENGALI_DIGITS):
        text = text.replace(d, str(i))
    return text


def parse_facebook_date(
    time_str: str,
    base_time: Optional[datetime.datetime] = None,
) -> Tuple[Optional[datetime.datetime], str]:
    """
    Parses relative or textual time strings into calculated datetime objects.

    :param time_str: Raw text extracted from Facebook post time attribute / tooltip / innerText
    :param base_time: Reference datetime for relative offsets (defaults to datetime.now())
    :return: (datetime object or None, original cleaned text)
    """
    if not time_str or not isinstance(time_str, str):
        return None, ""

    raw_str = time_str.strip().rstrip("\ufeff")
    if not raw_str:
        return None, ""

    text = normalize_bengali_digits(raw_str.lower())

    # Strip day names (e.g. "Monday, 10 October", "বুধ, ১০ অক্টোবর")
    text = re.sub(
        r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|সোম|মঙ্গল|বুধ|বৃহস্পতি|শুক্র|শনি|রবি)[,\s]+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Strip auxiliary tokens
    text = re.sub(r"\b(view post|edited|·|at|shared with public)\b", " ", text).strip()
    text = re.sub(r"\s+", " ", text)

    if base_time is None:
        base_time = datetime.datetime.now()

    # ISO Format
    if "t" in text and ("z" in text or "+" in text or "-" in text):
        try:
            iso_clean = raw_str.replace("Z", "+00:00")
            return datetime.datetime.fromisoformat(iso_clean), raw_str
        except Exception:
            pass

    # 1. Just now / Now / এইমাত্র
    if re.search(r"\b(just now|a moment ago|now|এইমাত্র)\b", text):
        return base_time, raw_str

    # 2. Seconds ago
    m = re.search(r"(\d+)\s*(?:s|sec|second|সেকেন্ড)s?(?:\s*(?:ago|আগে))?(?:\b|$|\s)", text)
    if m:
        return base_time - datetime.timedelta(seconds=int(m.group(1))), raw_str

    # 3. Minutes ago
    m = re.search(r"(\d+)\s*(?:m|min|minute|মিনিট)s?(?:\s*(?:ago|আগে))?(?:\b|$|\s)", text)
    if m:
        return base_time - datetime.timedelta(minutes=int(m.group(1))), raw_str

    # 4. Hours ago
    if re.search(r"\b(?:about\s+)?an?\s*(?:hr|hour)\s*(?:ago)?\b", text) or "১ ঘণ্টা আগে" in text or "1 ঘণ্টা আগে" in text:
        return base_time - datetime.timedelta(hours=1), raw_str
    m = re.search(r"(\d+)\s*(?:h|hr|hour|ঘণ্টা|ঘন্টা)s?(?:\s*(?:ago|আগে))?(?:\b|$|\s)", text)
    if m:
        return base_time - datetime.timedelta(hours=int(m.group(1))), raw_str

    # 5. Days ago
    if re.search(r"\b(?:about\s+)?a\s*day\s*(?:ago)?\b", text) or "১ দিন আগে" in text or "1 দিন আগে" in text:
        return base_time - datetime.timedelta(days=1), raw_str
    m = re.search(r"(\d+)\s*(?:d|day|দিন)s?(?:\s*(?:ago|আগে))?(?:\b|$|\s)", text)
    if m:
        return base_time - datetime.timedelta(days=int(m.group(1))), raw_str

    # 6. Weeks ago
    if re.search(r"\b(?:about\s+)?a\s*week\s*(?:ago)?\b", text) or "১ সপ্তাহ আগে" in text or "1 সপ্তাহ আগে" in text:
        return base_time - datetime.timedelta(weeks=1), raw_str
    m = re.search(r"(\d+)\s*(?:w|wk|week|সপ্তাহ)s?(?:\s*(?:ago|আগে))?(?:\b|$|\s)", text)
    if m:
        return base_time - datetime.timedelta(weeks=int(m.group(1))), raw_str

    # 7. Months ago
    m = re.search(r"(\d+)\s*(?:mo|month|মাস)s?(?:\s*(?:ago|আগে))?(?:\b|$|\s)", text)
    if m:
        return base_time - datetime.timedelta(days=int(m.group(1)) * 30), raw_str
    if re.search(r"\b(?:about\s+)?a\s*month\s*(?:ago)?\b", text) or "১ মাস আগে" in text or "1 মাস আগে" in text:
        return base_time - datetime.timedelta(days=30), raw_str

    # 8. Years ago
    m = re.search(r"(\d+)\s*(?:y|yr|year|বছর)s?(?:\s*(?:ago|আগে))?(?:\b|$|\s)", text)
    if m:
        return base_time - datetime.timedelta(days=int(m.group(1)) * 365), raw_str
    if re.search(r"\b(?:about\s+)?a\s*year\s*(?:ago)?\b", text) or "১ বছর আগে" in text or "1 বছর আগে" in text:
        return base_time - datetime.timedelta(days=365), raw_str

    # 9. Yesterday
    m = re.search(r"(?:yesterday|গতকাল)(?:\s+(\d{1,2}):(\d{2})(?:\s*(am|pm))?)?", text)
    if m:
        yesterday = base_time - datetime.timedelta(days=1)
        if m.group(1) and m.group(2):
            hour = int(m.group(1))
            minute = int(m.group(2))
            meridiem = (m.group(3) or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            return yesterday.replace(hour=hour, minute=minute, second=0, microsecond=0), raw_str
        return yesterday, raw_str

    # 10. Explicit date like "12 October 2024", "October 12, 2024", "12 Oct", "Oct 12"
    pattern = (
        r"(?:(\d{1,2})\s+([a-z]{3,9})|([a-z]{3,9})\s+(\d{1,2}))"
        r"(?:,?\s*(\d{4}))?"
        r"(?:\s+(\d{1,2}):(\d{2})(?:\s*(am|pm))?)?"
    )
    m = re.search(pattern, text)
    if m:
        d_str = m.group(1) or m.group(4)
        m_str = (m.group(2) or m.group(3) or "").lower()
        y_str = m.group(5)

        month_num = None
        for k, v in MONTH_MAP.items():
            if m_str.startswith(k):
                month_num = v
                break

        if d_str and month_num:
            day = int(d_str)
            year = int(y_str) if y_str else base_time.year
            hour = 0
            minute = 0
            if m.group(6) and m.group(7):
                hour = int(m.group(6))
                minute = int(m.group(7))
                meridiem = (m.group(8) or "").lower()
                if meridiem == "pm" and hour < 12:
                    hour += 12
                elif meridiem == "am" and hour == 12:
                    hour = 0

            try:
                dt = datetime.datetime(year, month_num, day, hour, minute, 0)
                return dt, raw_str
            except Exception:
                pass

    return None, raw_str
