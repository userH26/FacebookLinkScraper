"""
Core Facebook Link Scraper implementation using Playwright.
Features:
- Pure post permalink extraction (photo, post, reels URLs)
- Anti-ban human simulation: randomized smooth scrolling, natural cursor movements, variable pauses, and micro scroll-backs
- Network resilience: automatic recovery from network drops, weak signals, and page timeouts
- Incremental autosaving to disk (preserves all scraped links on interruption)
- RAM and memory management: off-screen DOM pruning and video unmounting
- Session persistence and cookie importing
"""

import datetime
import logging
import os
import random
import re
import time
from typing import Any, Dict, List, Optional, Set, Union

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from src.exporter import create_backup, save_to_csv
from src.session_manager import import_cookies_from_file, import_cuser_xs, interactive_login
from src.url_cleaner import clean_post_url, extract_post_id, is_post_url

logger = logging.getLogger("FacebookLinkScraper")


def check_internet_connection(timeout: float = 3.0) -> bool:
    """Checks if an active internet connection is reachable."""
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        return True
    except OSError:
        return False


def wait_for_internet_connection(max_wait_seconds: int = 120, poll_interval: float = 4.0) -> bool:
    """Waits for internet connection to be restored if dropped."""
    if check_internet_connection():
        return True
    logger.warning("Internet connection appears down. Waiting for connection recovery...")
    start_wait = time.time()
    while time.time() - start_wait < max_wait_seconds:
        time.sleep(poll_interval)
        if check_internet_connection():
            logger.info("Internet connection restored! Resuming...")
            return True
    logger.error("Network remained disconnected for %d seconds.", max_wait_seconds)
    return False


def normalize_target_url(url: str) -> str:
    """Normalizes a user-provided Facebook page URL or shorthand into a standard canonical URL."""
    if not url:
        return "https://www.facebook.com"
    clean = url.strip()
    if clean.startswith("fb.com"):
        clean = "https://www." + clean
    elif clean.startswith("facebook.com"):
        clean = "https://www." + clean
    elif clean.startswith("www.fb.com"):
        clean = "https://" + clean
    elif clean.startswith("www.facebook.com"):
        clean = "https://" + clean
    elif not clean.startswith("http://") and not clean.startswith("https://"):
        if "/" not in clean and "." not in clean:
            clean = f"https://www.facebook.com/{clean}"
        else:
            clean = "https://" + clean
    clean = clean.replace("://fb.com", "://www.facebook.com").replace("://www.fb.com", "://www.facebook.com")
    return clean


class FacebookLinkScraper:
    """
    Playwright-based scraper to extract Facebook post permalinks (photo, post, reels).
    """

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        headless: bool = False,
        timeout: int = 45000,
        session_dir: Optional[str] = "./fb_session",
        user_agent: Optional[str] = None,
        cookies_file: Optional[str] = None,
        c_user: Optional[str] = None,
        xs: Optional[str] = None,
    ):
        self.headless = headless
        self.timeout = timeout
        self.session_dir = os.path.abspath(session_dir) if session_dir else None
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.cookies_file = cookies_file
        self.c_user = c_user
        self.xs = xs

        self._playwright = None
        self._context: Optional[BrowserContext] = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def start(self):
        """Initializes Playwright browser context with persistent profile and anti-bot evasions."""
        if self._context:
            return

        self._playwright = sync_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-notifications",
        ]

        if self.session_dir:
            os.makedirs(self.session_dir, exist_ok=True)
            logger.info("Using session profile at: %s (Headless: %s)", self.session_dir, self.headless)
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.session_dir,
                headless=self.headless,
                args=launch_args,
                user_agent=self.user_agent,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
        else:
            browser = self._playwright.chromium.launch(
                headless=self.headless,
                args=launch_args,
            )
            self._context = browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )

        # Inject stealth evasions to mask automation flags and protect account from bot detection
        self._context.add_init_script(
            r"""() => {
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = {
                    runtime: {},
                    loadTimes: () => {},
                    csi: () => {},
                    app: {}
                };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
            }"""
        )

        if self.cookies_file:
            import_cookies_from_file(self._context, self.cookies_file)

        if self.c_user and self.xs:
            import_cuser_xs(self._context, self.c_user, self.xs)

    def stop(self):
        """Cleanly terminates the browser context and Playwright process to free RAM and resources."""
        try:
            if self._context:
                self._context.close()
                self._context = None
            if self._playwright:
                self._playwright.stop()
                self._playwright = None
        except Exception as e:
            logger.debug("Error during browser shutdown: %s", e)
        logger.info("Browser session cleanly terminated.")

    def login_interactively(self):
        """Launches a headfull browser window for manual login, saving session to session_dir."""
        if not self._context:
            self.start()
        interactive_login(self._context, self.session_dir)

    def dismiss_overlays(self, page: Page):
        """Dismisses cookie consent dialogs and removes blocking login banners."""
        try:
            selectors = [
                'div[role="dialog"] [aria-label="Close"]',
                'div[role="dialog"] [aria-label="close"]',
                '[aria-label="Decline optional cookies"]',
                '[aria-label="Allow all cookies"]',
                '[data-cookiebanner="accept_button"]',
            ]
            for selector in selectors:
                buttons = page.locator(selector)
                if buttons.count() > 0:
                    try:
                        buttons.first.click(timeout=400)
                    except Exception:
                        pass

            page.evaluate(
                r"""() => {
                    document.querySelectorAll('div').forEach(el => {
                        const style = window.getComputedStyle(el);
                        const pos = style.position;
                        const text = el.innerText || '';
                        if (
                            (pos === 'fixed' || pos === 'sticky') && (
                                text.includes('See more on Facebook') || 
                                text.includes('Create new account') ||
                                (text.includes('Log in') && (style.bottom === '0px' || style.top === '0px'))
                            ) && !el.querySelector('div[role="feed"]') && !el.querySelector('div[role="main"]')
                        ) {
                            try { el.remove(); } catch(e) {}
                        }
                    });
                    document.body.style.overflow = 'auto';
                }"""
            )
        except Exception:
            pass

    def handle_feed_recovery(self, page: Page) -> bool:
        """Checks for Facebook 'Something went wrong', 'Try Again', or 'Reload' buttons and clicks them."""
        try:
            reload_selectors = [
                'div[role="button"]:has-text("Reload Page")',
                'div[role="button"]:has-text("Try Again")',
                'div[role="button"]:has-text("Try again")',
                'div[role="button"]:has-text("পুনরায় চেষ্টা করুন")',
                'span:has-text("Try Again")',
            ]
            for sel in reload_selectors:
                btn = page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible():
                    logger.info("Found feed reload prompt on page. Clicking to recover feed...")
                    btn.first.click(timeout=1000)
                    time.sleep(3)
                    return True
        except Exception:
            pass
        return False

    def is_feed_loading(self, page: Page) -> bool:
        """Detects if Facebook is actively waiting for lazy-loaded feed content."""
        try:
            return page.evaluate(r"""() => {
                const spinners = document.querySelectorAll('div[role="progressbar"], svg[aria-label*="Loading"], svg[aria-label*="loading"], [data-visualcompletion="loading-state"]');
                for (const s of spinners) {
                    const rect = s.getBoundingClientRect();
                    if (rect.height > 0 && rect.top > 0 && rect.top < window.innerHeight + 500) {
                        return true;
                    }
                }
                return false;
            }""")
        except Exception:
            return False

    def prune_dom_and_media(self, page: Page):
        """
        Pauses and mutes active video streams to keep CPU/RAM usage low without
        breaking React DOM nodes or corrupting video playback components.
        """
        try:
            page.evaluate(
                r"""() => {
                    document.querySelectorAll('video').forEach(v => {
                        try {
                            if (!v.paused) v.pause();
                            v.muted = true;
                        } catch(e) {}
                    });
                }"""
            )
        except Exception:
            pass

    def extract_visible_candidates(self, page: Page) -> List[str]:
        """
        Locates timeline posts on screen and extracts raw post permalinks.
        Enforces user hierarchy per post card:
          1. If post has photos -> photo?fbid=...
          2. Else if post has videos/reels -> reel/...
          3. Else (text/status post) -> posts/pfbid...
        Deduplicates parent posts and comment timestamps to ensure 1 post = 1 link.
        """
        try:
            candidates = page.evaluate(
                r"""() => {
                    const isInvalidUrl = (h) => {
                        if (!h) return true;
                        const lower = h.toLowerCase();
                        if (lower.includes('&set=pb.') || lower.includes('/followers') || lower.includes('/following') || lower.includes('/reel/?s=tab')) return true;
                        if (lower.endsWith('/reel') || lower.endsWith('/reel/') || lower.endsWith('/photos') || lower.endsWith('/photos/')) return true;
                        if (lower.includes('/sharer.php') || lower.includes('/dialog/')) return true;
                        return false;
                    };

                    const isFeaturedCard = (card) => {
                        if (!card) return false;
                        // 1. Check for explicit Featured / ফিচার্ড headings
                        const headings = Array.from(card.querySelectorAll('h1, h2, h3, h4, [role="heading"]'));
                        for (const h of headings) {
                            const text = (h.innerText || '').trim().toLowerCase();
                            const aria = (h.getAttribute('aria-label') || '').trim().toLowerCase();
                            if (text === 'featured' || aria === 'featured' || text === 'ফিচার্ড' || aria === 'ফিচার্ড') {
                                return true;
                            }
                        }
                        // 2. Check if card begins with Featured text
                        const firstText = (card.innerText || '').trim().slice(0, 30).toLowerCase();
                        if (firstText.startsWith('featured') || firstText.startsWith('ফিচার্ড')) {
                            return true;
                        }
                        return false;
                    };

                    const findPostCard = (el) => {
                        // Standard Facebook feed unit class
                        const unit = el.closest('.x1yztbdb');
                        if (unit) {
                            const r = unit.getBoundingClientRect();
                            if (r.width >= 500 && r.height >= 100) return unit;
                        }
                        // Fallback: traverse up to container matching post width
                        let curr = el.parentElement;
                        while (curr && curr !== document.body) {
                            const r = curr.getBoundingClientRect();
                            if (r.width >= 500 && r.width <= 750 && r.height >= 150) {
                                const hasActions = curr.querySelector(
                                    'div[aria-label*="Like" i], div[aria-label*="Comment" i], div[aria-label*="Share" i], ' +
                                    'div[aria-label*="পছন্দ" i], div[aria-label*="মন্তব্য" i], div[aria-label*="শেয়ার" i]'
                                );
                                if (hasActions && !curr.closest('div[role="article"]')) return curr;
                            }
                            curr = curr.parentElement;
                        }
                        return el.parentElement;
                    };

                    const container = document.querySelector('div[role="main"]') || document.body;
                    const allLinks = Array.from(container.querySelectorAll('a[href]'));

                    const cardMap = new Map();

                    for (const a of allLinks) {
                        const h = a.href || '';
                        const aria = (a.getAttribute('aria-label') || '').toLowerCase();
                        if (isInvalidUrl(h) || aria.includes('cover photo') || aria.includes('profile cover')) continue;

                        const isPhoto = (h.includes('/photo') && h.includes('fbid=') && !h.includes('&set=pb.') && (h.includes('set=a.') || !h.includes('set=')));
                        const isReel = (h.includes('/reel/') && !h.endsWith('/reel/')) || (h.includes('/videos/') && !h.endsWith('/videos/')) || (h.includes('/watch') && h.includes('v='));
                        const isPost = h.includes('/posts/') || h.includes('story_fbid=');

                        if (!isPhoto && !isReel && !isPost) continue;

                        const rect = a.getBoundingClientRect();
                        if (rect.x < 350) continue; // Ignore left sidebar photos/grid

                        const card = findPostCard(a);
                        // Skip featured tiles and pinned highlights
                        if (isFeaturedCard(card) || a.closest('[aria-label*="Featured" i], [aria-label*="ফিচার্ড" i], [data-pagelet*="Featured" i]')) {
                            continue;
                        }

                        // Check if link is inside an actual comment container (not the post body)
                        const isComment = Boolean(a.closest('div[aria-label*="Comment by" i], div[aria-label*="মন্তব্য" i], ul, li'));

                        if (!cardMap.has(card)) {
                            cardMap.set(card, {
                                card: card,
                                photos: [],
                                reels: [],
                                headerPosts: [],
                                commentPosts: [],
                                top: card.getBoundingClientRect().top + window.scrollY
                            });
                        }

                        const entry = cardMap.get(card);
                        if (isPhoto && !isComment) {
                            entry.photos.push(h);
                        } else if (isReel) {
                            // Reel timestamp permalinks inside feed cards are valid reel URLs
                            entry.reels.push(h);
                        } else if (isPost) {
                            if (isComment) {
                                entry.commentPosts.push(h);
                            } else {
                                entry.headerPosts.push(h);
                            }
                        }
                    }

                    const entries = Array.from(cardMap.values());
                    entries.sort((a, b) => a.top - b.top);

                    const results = [];
                    for (const entry of entries) {
                        let chosen = null;

                        // Hierarchy: Reel > Photo > Header Post > Comment Post
                        // If card is a video/reel post, select the reel URL
                        if (entry.reels.length > 0) {
                            chosen = entry.reels[0];
                        } else if (entry.photos.length > 0) {
                            chosen = entry.photos[0];
                        } else if (entry.headerPosts.length > 0) {
                            chosen = entry.headerPosts[0];
                        } else if (entry.commentPosts.length > 0) {
                            chosen = entry.commentPosts[0];
                        }

                        if (chosen) {
                            results.push(chosen);
                        }
                    }

                    return results;
                }"""
            )
            return candidates or []
        except Exception as e:
            logger.debug("Error extracting visible candidates: %s", e)
            return []

    def scrape_post_urls(
        self,
        page_url: str,
        max_posts: int = 50,
        max_scrolls: int = 5000,
        output_file: Optional[str] = "post_urls.csv",
        fresh: bool = False,
        session_timeout: Optional[int] = None,
        start_date: Optional[Union[str, datetime.date]] = None,
        date: Optional[Union[str, datetime.date]] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Scrapes post permalinks (photo, post, reels URLs) continuously until target count is satisfied.
        If start_date is provided, navigates directly to that date using Facebook's date filters before scraping.
        Handles network delays, weak connections, network drops, and simulates human behavior.

        :param page_url: Target Facebook page URL or shorthand (e.g. 'fb.com/MyNagad')
        :param max_posts: Target number of post URLs to collect
        :param max_scrolls: Maximum scroll pagination iterations before terminating
        :param output_file: Output CSV file path
        :param fresh: If True, ignores and overwrites existing CSV file
        :param session_timeout: Max duration in seconds before automatic termination
        :param start_date: Target date to navigate to (e.g. '2026-09-01' or '2026 September 01')
        :param date: Alias for start_date
        :return: List of dictionaries with 'posturl'
        """
        if not self._context:
            raise RuntimeError("Scraper context is not initialized. Use 'with FacebookLinkScraper() as scraper:'")

        normalized_url = normalize_target_url(page_url)
        nav_date = start_date or date or kwargs.get("filter_date")

        logger.info("Target Facebook Page: %s", normalized_url)
        logger.info("Target Post Count:    %d", max_posts)
        if nav_date:
            logger.info("Target Start Date:    %s", nav_date)
        logger.info("Max Scroll Limit:     %d", max_scrolls)
        logger.info("Autosave Output:      %s", output_file or "None")

        # Step 0: Validate target navigation date early if provided
        parsed_target_date = None
        if nav_date:
            try:
                from src.filter_handler import parse_filter_date_string
                dt, year, month_name, day = parse_filter_date_string(str(nav_date))
                parsed_target_date = (dt, year, month_name, day)
                logger.info("Validated target navigation date: %s (%d %s %02d)", nav_date, year, month_name, day)
            except Exception as e:
                logger.error(
                    "Target date '%s' could not be parsed: %s. "
                    "Stopping script immediately before any changes are made.",
                    nav_date, e
                )
                return []

        # Pre-load existing records from CSV to prevent duplicate scraping and resume seamlessly
        seen_ids: Set[str] = set()
        existing_records: List[Dict[str, Any]] = []
        if output_file and os.path.exists(output_file) and not fresh:
            try:
                import csv
                with open(output_file, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row and "posturl" in row and row["posturl"]:
                            u = row["posturl"].strip()
                            pid = extract_post_id(u) or u
                            seen_ids.add(pid)
                            existing_records.append({"posturl": u})
                if existing_records:
                    logger.info("Found %d existing posts in %s.", len(existing_records), output_file)
            except Exception as e:
                logger.debug("Could not pre-load existing CSV: %s", e)

        # Calculate target posts needed
        if nav_date:
            # When an explicit navigation date is specified, collect max_posts starting from that date
            target_needed = max_posts
            if existing_records:
                logger.info("Found %d existing posts in %s. Collecting %d new posts starting from %s...",
                            len(existing_records), output_file, target_needed, nav_date)
            else:
                logger.info("Starting collection for target of %d posts from %s.", target_needed, nav_date)
        elif existing_records and len(existing_records) < max_posts:
            target_needed = max_posts - len(existing_records)
            logger.info("Resuming session: Found %d existing posts. Need %d more posts to satisfy target of %d.",
                        len(existing_records), target_needed, max_posts)
        elif existing_records and len(existing_records) >= max_posts:
            target_needed = max_posts
            logger.info("Existing file already contains %d posts. Collecting %d new posts...",
                        len(existing_records), target_needed)
        else:
            target_needed = max_posts
            logger.info("Starting collection for target of %d posts.", target_needed)

        start_time = time.time()
        page = self._context.new_page()

        # Step 1: Resilient Page Navigation with Retry & Backoff
        nav_success = False
        for attempt in range(1, 6):
            if not check_internet_connection():
                wait_for_internet_connection()

            try:
                logger.info("Navigating to %s (Attempt %d/5)...", normalized_url, attempt)
                page.goto(normalized_url, wait_until="domcontentloaded", timeout=self.timeout)
                nav_success = True
                break
            except Exception as e:
                logger.warning("Network delay or timeout during navigation (%s). Retrying in %ds...", e, attempt * 4)
                time.sleep(attempt * 4)

        if not nav_success:
            logger.error("Failed to connect to %s after 5 attempts due to persistent network issues.", normalized_url)
            page.close()
            return []

        # Human-like settling delay
        time.sleep(random.uniform(3.0, 4.5))
        self.dismiss_overlays(page)

        # Step 2: Date Navigation (if requested by user)
        if nav_date:
            dt, year, month_name, day = parsed_target_date
            logger.info("Navigating to target date via Facebook filter: %s (%d %s %02d)...", nav_date, year, month_name, day)
            date_filter_applied = False
            try:
                from src.filter_handler import apply_page_date_filter
                date_filter_applied = apply_page_date_filter(page, year, month_name, day)
            except Exception as e:
                logger.error("Exception occurred during date navigation to '%s': %s", nav_date, e)
                date_filter_applied = False

            if not date_filter_applied:
                logger.error(
                    "FAILED to navigate to target date '%s'. "
                    "Stopping script immediately before any changes are made.",
                    nav_date,
                )
                try:
                    page.close()
                except Exception:
                    pass
                return []

            logger.info("Feed successfully positioned at target date %s. Beginning post collection...", dt)

        # Step 3: Automatically create safety backup of existing file right before modifications begin
        if output_file and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            backup_file = create_backup(output_file)
            if backup_file:
                logger.info("Safety backup of existing records created at: %s", backup_file)

        collected_records: List[Dict[str, Any]] = []
        scroll_count = 0
        no_new_posts_streak = 0

        # Initial scroll to trigger Facebook feed mounting
        try:
            page.mouse.move(random.randint(550, 750), random.randint(350, 550), steps=random.randint(5, 10))
            page.mouse.wheel(0, 900)
            time.sleep(random.uniform(2.0, 3.2))
        except Exception:
            pass

        try:
            # Main Continuous Scraping Loop - Doesn't stop until target is satisfied
            while len(collected_records) < target_needed and scroll_count < max_scrolls:
                if session_timeout and (time.time() - start_time) > session_timeout:
                    logger.info("Session timeout reached (%d seconds). Terminating session.", session_timeout)
                    break

                scroll_count += 1
                self.dismiss_overlays(page)

                # Extract candidates with network resilience
                raw_candidates = []
                try:
                    raw_candidates = self.extract_visible_candidates(page)
                except Exception as e:
                    err_msg = str(e).lower()
                    if "disconnected" in err_msg or "network" in err_msg or "timeout" in err_msg:
                        logger.warning("Network delay or disconnect encountered during extraction (%s). Checking connection...", e)
                        wait_for_internet_connection()
                        try:
                            page.reload(wait_until="domcontentloaded", timeout=self.timeout)
                            time.sleep(3)
                            self.dismiss_overlays(page)
                        except Exception:
                            pass
                    else:
                        logger.warning("Transient browser delay during extraction: %s. Pausing 3s...", e)
                        time.sleep(3)
                    continue

                new_in_round = 0
                for raw_url in raw_candidates:
                    clean_url = clean_post_url(raw_url)
                    if not is_post_url(clean_url):
                        continue

                    post_id = extract_post_id(clean_url) or clean_url
                    if post_id in seen_ids:
                        continue

                    seen_ids.add(post_id)
                    record = {"posturl": clean_url}
                    collected_records.append(record)
                    new_in_round += 1

                    total_so_far = len(existing_records) + len(collected_records)
                    target_total = len(existing_records) + target_needed
                    logger.info("[%d/%d] %s", total_so_far, target_total, clean_url)

                    # Incremental Autosave: Guarantee zero data loss if network drops or session ends
                    if output_file and len(collected_records) % 2 == 0:
                        total_records = existing_records + collected_records
                        save_to_csv(total_records, output_file)

                    if len(collected_records) >= target_needed:
                        logger.info("Satisfied target goal! Collected %d posts (Total in file: %d).",
                                    len(collected_records), total_so_far)
                        break

                if len(collected_records) >= target_needed:
                    break

                # Dynamic Recovery on Stagnation & Weak Network Handling
                if new_in_round == 0:
                    no_new_posts_streak += 1
                    logger.debug("No new posts discovered in scroll round %d (Streak: %d)", scroll_count, no_new_posts_streak)

                    # 1. Check if Facebook is showing a feed reload prompt ("Try Again" / "Reload")
                    self.handle_feed_recovery(page)

                    # 2. Shake Scroll Recovery: if feed lazy loading stalls, shake scroll
                    if no_new_posts_streak >= 4:
                        try:
                            logger.info("Feed lazy-loading pause... Triggering shake recovery (Streak %d)", no_new_posts_streak)
                            page.mouse.wheel(0, -300)
                            page.evaluate("window.scrollBy(0, -300);")
                            time.sleep(random.uniform(1.8, 2.5))
                            page.mouse.wheel(0, 800)
                            time.sleep(random.uniform(1.5, 2.2))
                        except Exception:
                            pass

                    if no_new_posts_streak >= 35:
                        logger.info("Reached end of available page feed after 35 recovery attempts.")
                        break
                else:
                    no_new_posts_streak = 0

                # Human-like browsing simulation:
                # 1. Randomized scroll distance
                scroll_step = random.randint(600, 1050)

                # 2. Natural mouse movement across feed with intermediate steps
                try:
                    mouse_x = random.randint(450, 780)
                    mouse_y = random.randint(280, 680)
                    page.mouse.move(mouse_x, mouse_y, steps=random.randint(6, 12))

                    # Wheel in micro-increments to emulate natural finger scrolling
                    part1 = int(scroll_step * random.uniform(0.4, 0.6))
                    part2 = scroll_step - part1
                    page.mouse.wheel(0, part1)
                    time.sleep(random.uniform(0.08, 0.16))
                    page.mouse.wheel(0, part2)
                    page.evaluate(f"window.scrollBy({{ top: {scroll_step}, behavior: 'smooth' }});")
                except Exception as e:
                    logger.debug("Mouse/scroll event skipped: %s", e)

                # 3. Randomized delay between scrolls (simulates realistic reading speed)
                delay = random.uniform(2.2, 3.8)
                time.sleep(delay)

                # 4. Occasional human hesitation & micro-scrollback (every 7-9 scrolls)
                if scroll_count % 8 == 0:
                    try:
                        hesitation = random.uniform(3.5, 5.5)
                        logger.debug("Human hesitation pause: %.1fs", hesitation)
                        time.sleep(hesitation)
                        # Micro scroll up (100-200px) as if reviewing a post
                        page.mouse.wheel(0, -180)
                        page.evaluate("window.scrollBy(0, -180);")
                        time.sleep(random.uniform(1.0, 1.8))
                        page.mouse.wheel(0, 180)
                    except Exception:
                        pass

                # 5. Prune DOM every 4 scrolls to keep RAM usage low and avoid tab crashes
                if scroll_count % 4 == 0:
                    self.prune_dom_and_media(page)

            logger.info("Scraping completed. Collected %d posts in this session.", len(collected_records))

            # Final persistence to CSV
            if output_file:
                total_records = existing_records + collected_records
                save_to_csv(total_records, output_file)
                logger.info("Saved %d total records (%d newly collected) to CSV: %s",
                            len(total_records), len(collected_records), output_file)

            return collected_records

        finally:
            try:
                page.close()
            except Exception:
                pass
            self.stop()

