# Facebook Link Scraper

A robust, modular Python scraper built on Playwright to extract permalinks and authentic timestamps from Facebook pages with Page Date Filters, session persistence/importing, RAM optimization, and explicit session termination.

---

## Key Features

1. **Session Importing & Persistence**:
   - **Interactive Browser Login**: `python main.py --login` opens a browser window and saves the authenticated profile into `./fb_session`.
   - **JSON Cookie Import**: Import cookies exported from browser extensions (*Cookie-Editor*, *EditThisCookie*, or Playwright `storage_state.json`) via `--import-cookies cookies.json`.
   - **Direct Cookie Auth**: Pass Facebook's session cookies directly via `--c-user <id> --xs <secret>`.
2. **Page Date Filter**:
   - Filter directly by page date (e.g. `--filter-date "2026 October 12"` or `--filter-date 2026-10-12`).
   - Automatically clicks Facebook's native page **Filters** dialog (Year, Month, Day) and falls back to smart timeline scanning if the filter button is absent, collecting all earlier posts starting from that date.
3. **Authentic Hover Timestamp Extraction**:
   - Posts on Facebook display relative times (e.g., `"6h"`). Hovering over this timestamp reveals the full authentic timestamp (e.g., `"Tuesday 13 October 2026 at 15:02"`).
   - The scraper automatically triggers the hover tooltip and saves both `original_timestamp`, `relative_time`, and `parsed_datetime` alongside `posturl`.
4. **RAM Optimization & Session Termination**:
   - Scrolling Facebook continuously bloats DOM nodes, video buffers, and memory. The scraper actively prunes off-screen DOM nodes and unmounts videos during scrolling.
   - Enforces clean session termination based on `--max-posts`, `--max-scrolls`, or `--session-timeout`. Playwright contexts and browser processes are cleanly destroyed upon completion to prevent lingering background processes.
5. **Headless vs Headfull Modes**:
   - Switch between `--headless` (background execution) and `--headfull` (visible browser GUI) via CLI flags or Python options.

---

## Installation

### 1. Prerequisites
- **Python 3.10+** (Python 3.8+ supported)
- **Git**

### 2. Clone the Repository
```bash
git clone https://github.com/userH26/FacebookLinkScraper.git
cd FacebookLinkScraper
```

### 3. Set Up Virtual Environment
- **Linux / macOS**:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```
- **Windows (PowerShell / CMD)**:
  ```powershell
  python -m venv .venv
  .venv\Scripts\activate
  ```

### 4. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 5. Install Playwright Browser Binaries
Playwright requires Chromium browser binaries to run:
```bash
playwright install chromium
```
> **Note for Linux users:** If required system dependencies are missing, run:
> ```bash
> playwright install-deps chromium
> ```

---

## Project Structure

```
LinkScraper/
├── src/
│   ├── __init__.py           # Package exports
│   ├── scraper.py            # FacebookLinkScraper engine & DOM hover logic
│   ├── filter_handler.py     # Native Page Date Filter interaction & date parsing
│   ├── session_manager.py    # Cookie JSON & credential importing
│   ├── url_cleaner.py        # Canonicalization & tracking removal
│   ├── date_parser.py        # Relative & absolute date parsing
│   └── exporter.py           # CSV, JSON, and TXT exporters
├── backup/                   # Previous scripts archived safely
├── fb_session/               # Persistent browser session profile
├── main.py                   # Primary CLI and IDE run target
├── facebook_link_scraper.py  # Backward-compatible entry point
├── requirements.txt          # Python dependencies
└── README.md
```

---

## How to Import Session Info

### Method 1: Interactive Browser Login (Recommended)
```bash
python main.py --login
```
A browser window opens to Facebook. Log into your account and press **Enter** in your terminal. All cookies and storage tokens are saved in `./fb_session` for future runs.

### Method 2: Import from Cookie-Editor / JSON File
Export your Facebook cookies from Chrome using the **Cookie-Editor** extension (Export -> Export as JSON) and run:
```bash
python main.py --page "https://www.facebook.com/MyNagad" --import-cookies cookies.json
```

### Method 3: Direct `c_user` and `xs` Values
```bash
python main.py --c-user 1000123456789 --xs 2%3Aabc123def456%3A2
```

---

## Page Date Filter Usage

To start scraping from a specific date (e.g., October 12, 2026) and collect all earlier posts:

```bash
# Example with fb.com/MyNagad starting from 2026 October 12:
python main.py --page "https://www.facebook.com/MyNagad" --filter-date "2026 October 12" --max-posts 30
```
Or using ISO format:
```bash
python main.py --page "https://www.facebook.com/MyNagad" --filter-date "2026-10-12" --max-posts 30
```

---

## Headless vs Headfull Execution

- **Headfull (Visible Window)**:
  ```bash
  python main.py --headfull --max-posts 20
  ```
- **Headless (Background)**:
  ```bash
  python main.py --headless --max-posts 20
  ```

---

## Controlling RAM & Session Termination

Prevent memory leaks and runaway scrolling by specifying bounds:
```bash
python main.py --max-posts 50 --max-scrolls 30 --session-timeout 300
```
- `--max-posts`: Stops immediately once N posts are captured.
- `--max-scrolls`: Maximum scroll rounds before terminating.
- `--session-timeout`: Timeout in seconds before auto-closing.

---

## Output Format (`post_urls.csv`)

The resulting CSV contains rich post information:

| posturl | original_timestamp | relative_time | parsed_datetime |
| :--- | :--- | :--- | :--- |
| `https://www.facebook.com/photo?fbid=1137510645299966` | `Tuesday 13 October 2026 at 15:02` | `6h` | `2026-10-13 15:02:00` |
| `https://www.facebook.com/MyNagad/posts/pfbid0xyz...` | `Monday 12 October 2026 at 18:30` | `1d` | `2026-10-12 18:30:00` |

---

