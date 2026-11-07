"""
URL cleaning and post ID extraction utilities for Facebook.
"""

import re
import urllib.parse
from typing import Optional, Set

# Query parameters that should be preserved for identifying posts when paths lack the ID
ESSENTIAL_QUERY_PARAMS: Set[str] = {
    "fbid",
    "story_fbid",
    "v",
    "id",
    "post_id",
}

# Substrings that disqualify an anchor tag href from being a main post permalink
INVALID_LINK_PATTERNS = [
    "/comments/",
    "/reply/",
    "/share/",
    "sharer.php",
    "/dialog/",
    "/hashtag/",
    "/about",
    "/followers",
    "/following",
    "/reviews",
    "/mentions",
]

# Post URL path regex patterns
POST_PATH_REGEX = re.compile(
    r"/(?:posts|photos|photo|reel|reels|videos|watch|permalink)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def clean_post_url(url: str) -> str:
    """
    Cleans tracking query parameters (__cft__, __tn__, mibextid, ref, etc.)
    and normalizes Facebook post URLs into clean desktop permalinks.

    :param url: Raw URL string extracted from Facebook DOM
    :return: Sanitized and normalized canonical Facebook post URL
    """
    if not url or not isinstance(url, str):
        return ""

    raw_url = url.strip()
    raw_lower = raw_url.lower()

    # Reject standalone comment paths if not a post/reel/photo permalink
    if any(p in raw_lower for p in ("/comments/", "/comment/", "/reply/")):
        if not any(seg in raw_lower for seg in ("/posts/", "/reel/", "/photo", "story_fbid=")):
            return ""

    # Normalize mobile subdomains to standard desktop www
    normalized = re.sub(
        r"^https?://(?:m|mobile|mbasic)\.facebook\.com",
        "https://www.facebook.com",
        raw_url,
    )

    try:
        parsed = urllib.parse.urlparse(normalized)
        if not parsed.netloc:
            return ""

        q_params = urllib.parse.parse_qs(parsed.query)

        # Filter query params to keep only essential post identifiers
        filtered_query = {
            k: v for k, v in q_params.items() if k in ESSENTIAL_QUERY_PARAMS
        }

        # Format query string
        new_query = urllib.parse.urlencode(filtered_query, doseq=True)
        clean_path = parsed.path.rstrip("/")

        # Normalize video permalinks to unified /reel/<id> format
        video_match = re.match(r"^/[^/]+/videos/(\d+)$", clean_path)
        if video_match:
            return f"https://www.facebook.com/reel/{video_match.group(1)}"
        if clean_path.startswith("/watch") and "v" in filtered_query:
            v_val = filtered_query["v"]
            v_id = v_val[0] if isinstance(v_val, list) else v_val
            return f"https://www.facebook.com/reel/{v_id}"

        cleaned = urllib.parse.urlunparse((
            parsed.scheme or "https",
            "www.facebook.com" if "facebook.com" in parsed.netloc else parsed.netloc,
            clean_path,
            "",
            new_query,
            "",
        ))
        return cleaned
    except Exception:
        return raw_url


def extract_post_id(url: str) -> str:
    """
    Extracts the unique Facebook Post / Photo / Reel / Video ID from a URL.

    :param url: Post URL string
    :return: Unique post ID if found, else empty string
    """
    if not url:
        return ""

    try:
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)

        for param in ("story_fbid", "fbid", "v", "post_id"):
            if param in query_params and query_params[param]:
                return query_params[param][0]

        # Check path patterns like /posts/12345678, /reel/123456, etc.
        match = POST_PATH_REGEX.search(parsed.path)
        if match:
            candidate = match.group(1)
            # Avoid matching words like 'photos' or 'videos' without ID
            if candidate not in {"posts", "photos", "photo", "reel", "reels", "videos", "watch", "permalink"}:
                return candidate

        # Fallback regex search across entire string
        fallback_match = re.search(r"[?&](?:fbid|story_fbid|v)=([0-9A-Za-z_-]+)", url)
        if fallback_match:
            return fallback_match.group(1)

    except Exception:
        pass

    return ""


def is_post_url(url: str) -> bool:
    """
    Checks if a URL is likely a permalink to an individual Facebook post/media.

    :param url: URL to inspect
    :return: True if the URL points to a post/media item, False otherwise
    """
    if not url or not isinstance(url, str):
        return False

    url_lower = url.lower()

    # Reject obvious non-post URLs
    if any(pattern in url_lower for pattern in INVALID_LINK_PATTERNS):
        return False

    parsed = urllib.parse.urlparse(url_lower)
    path = parsed.path.rstrip("/")

    # Reject photo grid previews like set=pb.
    if "set=pb." in url_lower:
        return False

    # Tab pages like /pagename/photos, /pagename/videos, /pagename/reels, /pagename/about, /reel, /reels
    tab_names = {
        "photos", "videos", "reels", "reel", "about", "followers", "following",
        "reviews", "mentions", "community", "events", "live_videos", "posts",
    }
    path_segments = [s for s in path.split("/") if s]
    if path_segments and path_segments[-1] in tab_names and not any(k in parsed.query for k in ("fbid=", "story_fbid=", "v=")):
        return False

    # Standalone navigation /reel or /posts
    if len(path_segments) == 1 and path_segments[0] in tab_names:
        return False

    # Check for valid post indicators with an ID segment
    for seg in ("posts", "permalink", "reel", "reels", "watch", "videos"):
        if seg in path_segments and len(path_segments) > path_segments.index(seg) + 1:
            return True

    if "photos" in path_segments and len(path_segments) > path_segments.index("photos") + 1:
        return True

    # Photo permalink with fbid
    if ("photo" in path_segments or "photo.php" in path) and "fbid=" in parsed.query:
        return True

    if any(param in parsed.query for param in ("story_fbid=", "v=")):
        return True

    return False
