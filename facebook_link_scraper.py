"""
Backward compatibility wrapper for FacebookLinkScraper.
Delegates to modular components in `src/`.
"""

from src import (
    FacebookLinkScraper,
    clean_post_url,
    extract_post_id,
    is_post_url,
    parse_facebook_date,
    normalize_bengali_digits,
    save_to_csv,
    save_to_json,
    save_to_txt,
)
from main import main

if __name__ == "__main__":
    main()
