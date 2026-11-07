"""
Main entry point for Facebook Link Scraper.
Can be executed directly from IDE (e.g., PyCharm) or via Command Line Interface (CLI).
Supports flexible CLI syntax like:
  python main.py -page "fb.com/MyNagad" -50
  python main.py fb.com/MyNagad 50
  python main.py -p "https://www.facebook.com/MyNagad" -mp 50
"""

import argparse
import datetime
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Union

from src.exporter import create_backup
from src.scraper import FacebookLinkScraper, normalize_target_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Main")


def parse_date(date_str: Optional[str]) -> Optional[datetime.date]:
    """Parses a YYYY-MM-DD date string into a datetime.date object."""
    if not date_str:
        return None
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError:
        logger.error("Invalid date format: '%s'. Expected format: YYYY-MM-DD (e.g., 2024-01-15)", date_str)
        sys.exit(1)


def preprocess_cli_args(argv: List[str]) -> List[str]:
    """
    Preprocesses command-line arguments to support flexible shorthand syntax:
    - '-<number>' like '-50' -> ['-mp', '50']
    - Positional numbers (e.g., '50') -> ['-mp', '50']
    - Positional target pages (e.g., 'fb.com/MyNagad') -> ['-page', 'fb.com/MyNagad']
    """
    processed: List[str] = []
    has_page_flag = False
    has_posts_flag = False

    # Check which primary flags are already supplied
    for arg in argv:
        if arg in ("-p", "-page", "--page"):
            has_page_flag = True
        elif arg in ("-mp", "-max-posts", "--max-posts", "-n", "-count") or re.match(r"^-\d+$", arg):
            has_posts_flag = True

    i = 0
    while i < len(argv):
        arg = argv[i]

        # Handle -<number> shorthand (e.g., -50, -30, -100)
        if re.match(r"^-\d+$", arg):
            processed.extend(["-mp", arg[1:]])
            i += 1
            continue

        # If it's a known option flag starting with '-'
        if arg.startswith("-"):
            processed.append(arg)
            i += 1
            continue

        # Positional arguments:
        if not has_page_flag and ("fb.com" in arg or "facebook.com" in arg or "/" in arg or not arg.isdigit()):
            processed.extend(["-page", arg])
            has_page_flag = True
            i += 1
            continue
        elif not has_posts_flag and arg.isdigit():
            processed.extend(["-mp", arg])
            has_posts_flag = True
            i += 1
            continue
        else:
            processed.append(arg)
            i += 1

    return processed


def run_scraper(
    page_url: str = "https://www.facebook.com/bbcnews",
    max_posts: int = 50,
    max_scrolls: int = 5000,
    output_file: str = "post_urls.csv",
    fresh: bool = False,
    headless: bool = False,
    session_dir: str = "./fb_session",
    cookies_file: Optional[str] = None,
    c_user: Optional[str] = None,
    xs: Optional[str] = None,
    session_timeout: Optional[int] = None,
    start_date: Optional[Union[str, datetime.date]] = None,
    **kwargs,
) -> List[Dict[str, Any]]:
    """
    Executes the Facebook link scraping workflow.
    """
    canonical_url = normalize_target_url(page_url)

    print("=" * 65)
    print("Facebook Link Scraper")
    print(f"Target Page:        {canonical_url}")
    print(f"Goal:               {max_posts} post links (photo, post, reels)")
    if start_date:
        print(f"Target Start Date:  {start_date}")
    print(f"Max Scrolls:        {max_scrolls}")
    print(f"Browser Mode:       {'Headless' if headless else 'Headfull (Visible Window)'}")
    print(f"Session Profile:    {session_dir}")
    if cookies_file:
        print(f"Importing Cookies:  {cookies_file}")
    if c_user:
        print(f"c_user Session:     {c_user[:6]}...")
    print(f"Output File:        {output_file}")
    if output_file and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
        base, ext = os.path.splitext(output_file)
        print(f"Safety Backup:      {base}_backup{ext}")
    if fresh:
        print("Scrape Mode:        Fresh (Overwriting existing file)")
    else:
        print("Scrape Mode:        Resume / Continuous (Network resilient & Anti-ban)")
    print("=" * 65)

    with FacebookLinkScraper(
        headless=headless,
        session_dir=session_dir,
        cookies_file=cookies_file,
        c_user=c_user,
        xs=xs,
    ) as scraper:
        records = scraper.scrape_post_urls(
            page_url=canonical_url,
            max_posts=max_posts,
            max_scrolls=max_scrolls,
            output_file=output_file,
            fresh=fresh,
            session_timeout=session_timeout,
            start_date=start_date,
        )

    if start_date and not records:
        print("\n" + "=" * 65)
        print(f"[STOPPED] Could not navigate to target date '{start_date}'.")
        print("Scraper aborted before making any changes to data or output files.")
        print("=" * 65)
        return []

    print("\n" + "=" * 65)
    print(f"Completed! Collected {len(records)} posts in this run.")
    if output_file and records:
        print(f"Results saved to: {output_file}")
    print("=" * 65)
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrapes Facebook post permalinks (photo, post, reels URLs) continuously until target count is satisfied."
    )
    parser.add_argument(
        "-p", "-page", "--page",
        dest="page",
        type=str,
        default="https://www.facebook.com/bbcnews",
        help="Target Facebook page URL or shorthand (e.g., 'fb.com/MyNagad' or 'https://www.facebook.com/bbcnews')",
    )
    parser.add_argument(
        "-mp", "-max-posts", "--max-posts", "-n", "-count",
        dest="max_posts",
        type=int,
        default=50,
        help="Target number of post URLs to collect (e.g. -50 or -mp 50) (default: 50)",
    )
    parser.add_argument(
        "-ms", "-max-scrolls", "--max-scrolls",
        dest="max_scrolls",
        type=int,
        default=5000,
        help="Maximum scroll iterations before terminating session (default: 5000)",
    )
    parser.add_argument(
        "-o", "-output", "--output",
        dest="output",
        type=str,
        default="post_urls.csv",
        help="Output CSV file path (default: post_urls.csv)",
    )
    parser.add_argument(
        "-fresh", "--fresh", "-overwrite", "--overwrite",
        dest="fresh",
        action="store_true",
        help="Start a fresh scrape session, ignoring and overwriting existing CSV",
    )
    parser.add_argument(
        "-s", "-session-dir", "--session-dir",
        dest="session_dir",
        type=str,
        default="./fb_session",
        help="Directory to store persistent login profile and cookies (default: ./fb_session)",
    )
    parser.add_argument(
        "-ic", "-import-cookies", "--import-cookies", "-cookies-file", "--cookies-file",
        dest="cookies_file",
        type=str,
        default=None,
        help="Path to JSON cookies file (Cookie-Editor, EditThisCookie, or storage_state.json)",
    )
    parser.add_argument(
        "-cu", "-c-user", "--c-user",
        dest="c_user",
        type=str,
        default=None,
        help="Facebook c_user authentication cookie value",
    )
    parser.add_argument(
        "-xs", "-xs", "--xs",
        dest="xs",
        type=str,
        default=None,
        help="Facebook xs authentication cookie value",
    )
    parser.add_argument(
        "-st", "-session-timeout", "--session-timeout",
        dest="session_timeout",
        type=int,
        default=None,
        help="Max duration in seconds before automatically terminating session",
    )

    # Browser mode switches: -hl/--headless and -hf/--headfull
    browser_mode = parser.add_mutually_exclusive_group()
    browser_mode.add_argument(
        "-hl", "-headless", "--headless",
        dest="headless",
        action="store_true",
        help="Run browser in headless background mode",
    )
    browser_mode.add_argument(
        "-hf", "-headfull", "-headful", "--headfull", "--headful", "--no-headless",
        dest="headfull",
        action="store_true",
        help="Run browser with visible GUI window (headfull mode)",
    )

    parser.add_argument(
        "-l", "-login", "--login",
        dest="login",
        action="store_true",
        help="Open an interactive browser window to log in to Facebook and save session.",
    )

    # Target date navigation flag (supports -sd, -date, -d, -start-date, -fd, -filter-date)
    parser.add_argument(
        "-sd", "-start-date", "--start-date", "-date", "--date", "-d", "-fd", "-filter-date", "--filter-date",
        dest="start_date",
        type=str,
        default=None,
        help="Target date to navigate to before scraping (e.g. -sd '2026-09-01' or -date '2026 September 01')",
    )
    parser.add_argument("-ed", "-end-date", "--end-date", dest="end_date", default=None, help=argparse.SUPPRESS)

    return parser


def main(cli_args: Optional[List[str]] = None):
    if cli_args is None:
        cli_args = sys.argv[1:]

    processed_args = preprocess_cli_args(cli_args)
    parser = build_parser()
    args = parser.parse_args(processed_args)

    # Determine headless mode: default to False (headfull) if not specified or if --headfull chosen
    is_headless = False
    if args.headless:
        is_headless = True
    elif args.headfull:
        is_headless = False

    # Interactive login mode
    if args.login:
        with FacebookLinkScraper(headless=False, session_dir=args.session_dir) as scraper:
            scraper.login_interactively()
        return

    records = run_scraper(
        page_url=args.page,
        max_posts=args.max_posts,
        max_scrolls=args.max_scrolls,
        output_file=args.output,
        fresh=args.fresh,
        headless=is_headless,
        session_dir=args.session_dir,
        cookies_file=args.cookies_file,
        c_user=args.c_user,
        xs=args.xs,
        session_timeout=args.session_timeout,
        start_date=args.start_date,
    )
    if args.start_date and not records:
        return 1
    return 0


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        sys.exit(exit_code)

