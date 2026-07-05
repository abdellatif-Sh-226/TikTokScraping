================================================================================
                    TIKTOK SCRAPER - COMPLETE PROJECT GUIDE
================================================================================


================================================================================
TABLE OF CONTENTS
================================================================================
  1.  requirements.txt    - What libraries we need
  2.  config.py           - All settings in one place
  3.  models.py           - The data shapes (Profile, Video, etc.)
  4.  utils.py            - Helper tools (logging, retry, JSON)
  5.  scraper.py          - The main engine (Playwright browser automation)
  6.  main.py             - The entry point (what you run)
  7.  How to use the project

================================================================================
1.  requirements.txt
================================================================================

This file lists the Python packages that must be installed:

    playwright>=1.40.0
    pydantic>=2.0.0

- playwright:  Controls a real web browser (Chromium) so we can visit TikTok
               pages, scroll, click, and read data just like a human would.
- pydantic:    Helps us define data models with validation. Makes it easy to
               convert scraped data to JSON.

Install with:  pip install -r requirements.txt
Then install browser:  python -m playwright install chromium


================================================================================
2.  config.py  -  ALL SETTINGS IN ONE PLACE
================================================================================

WHY THIS FILE EXISTS:
---------------------
Hardcoding values (like CSS selectors, timeouts, file paths) inside your
main code is bad practice. If TikTok changes its HTML structure or you want
to change a timeout, you'd have to hunt through hundreds of lines of code.
This file centralises everything.

LINE-BY-LINE:

    from dataclasses import dataclass, field

A Python "dataclass" is a simple way to create a class that mainly holds
data. It automatically creates __init__ and __repr__ methods.

    @dataclass
    class TimeoutConfig:
        page_load: int = 15_000    # 15 seconds
        element_appear: int = 10_000  # 10 seconds
        scroll_pause: int = 2_000    # 2 seconds between scrolls
        retry_delay: int = 2_000     # 2 seconds before retrying

These are all time values (in milliseconds) that control how long the
scraper waits for various things.

    @dataclass
    class RetryConfig:
        max_attempts: int = 3
        backoff_factor: float = 1.5

If something fails (like a page load), we try again. This says "try 3 times,
and each time wait longer (1.5x the previous wait)."

    @dataclass
    class ScrollConfig:
        max_scrolls: int = 20
        scroll_amount: int = 1000

TikTok's profile page loads videos as you scroll down (lazy loading).
This controls how many times we scroll (20) and how many pixels each
scroll moves (1000).

    @dataclass
    class OutputConfig:
        output_dir: str = "output"
        profile_filename: str = "profile_{username}.json"
        video_filename: str = "video_{id}.json"

Where to save the scraped data. The {username} and {id} placeholders get
filled in automatically.

    @dataclass
    class Selectors:

CSS selectors that tell Playwright which HTML elements to read. For example:

        follower_count: str = '[data-e2e="followers-count"]'

This means "find an HTML element that has data-e2e='followers-count'"
and read its text. TikTok uses data-e2e attributes to mark important parts
of the page.

IMPORTANT: If TikTok changes its HTML structure, you UPDATE THIS FILE,
not the scraper code. This is the only place you need to change selectors.

    @dataclass
    class Config:
        timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
        retry: RetryConfig = field(default_factory=RetryConfig)
        ...
        browser_headless: bool = True

This is the "master config" that contains all the smaller configs.
browser_headless=True means the browser runs invisibly in the background.
Set to False to see the browser window.

    CONFIG = Config()

This creates one global config object that all other modules can import.
It's called a "singleton" - there is only one.


================================================================================
3.  models.py  -  THE DATA SHAPES
================================================================================

WHY THIS FILE EXISTS:
---------------------
When we scrape data, we need to store it in a structured way. This file
defines the "blueprints" for that data. We use Pydantic because it:
- Validates data types automatically
- Converts to JSON easily (.model_dump() and .model_dump_json())
- Is widely used and well-documented

LINE-BY-LINE:

    from pydantic import BaseModel, Field
    from datetime import datetime
    from typing import List, Optional

    class VideoTile(BaseModel):

A "VideoTile" represents ONE video in the profile page grid. It's a smaller
amount of data compared to a full video detail page.

        url: str = ""
        cover_image: Optional[str] = None
        description: str = ""
        plays: str = ""

Each field has a type and a default value. Optional[str] means it can be
None (if we couldn't find it on the page).

    class VideoDetail(BaseModel):

Represents data from a TikTok video DETAIL page (the page you get when you
click on a video). Has many fields:

        id: str = ""
        description: str = ""
        author_username: Optional[str] = None
        author_avatar: Optional[str] = None
        plays: str = ""
        likes: str = ""
        comments: str = ""
        shares: str = ""
        saves: str = ""
        sound: Optional[str] = None
        date: Optional[str] = None
        scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

The "scraped_at" field is special: it automatically records the current
time when you create a VideoDetail object. The default_factory runs the
lambda function to get the current time.

    class Profile(BaseModel):

Represents a TikTok profile page. Contains:

        username: str = ""
        nickname: str = ""
        avatar: Optional[str] = None
        bio: str = ""
        follower_count: str = ""
        following_count: str = ""
        like_count: str = ""
        video_count: str = ""
        recent_videos: List[VideoTile] = Field(default_factory=list)

The "recent_videos" field is a list of VideoTile objects. It starts as an
empty list and gets filled with the videos we find on the page.


================================================================================
4.  utils.py  -  HELPER TOOLS
================================================================================

WHY THIS FILE EXISTS:
---------------------
Contains small reusable functions that don't belong to any specific part of
the scraper. These are "cross-cutting concerns" - things used everywhere.

LINE-BY-LINE:

LOGGING:

    def get_logger(name: str) -> logging.Logger:

Creates a logger that writes messages both to:
- The console (terminal) - shows INFO level and above
- A file (logs/tiktok_scraper.log) - shows DEBUG level and above

The logger is "idempotent" - if you ask for the same name twice, you get
the same logger back. This prevents duplicate log messages.

Log levels from lowest to highest:
  DEBUG   - detailed info for debugging
  INFO    - general progress (e.g., "Profile scraped")
  WARNING - something unexpected but non-fatal
  ERROR   - something went wrong
  CRITICAL - something catastrophic

RETRY DECORATOR:

    def async_retry(max_attempts=None, base_delay_ms=None, ...):

A "decorator" is a function that wraps another function to add behavior.
This one adds retry logic to async functions.

HOW IT WORKS:
  1. Try to run the function
  2. If it fails with an exception, wait a bit
  3. Try again (up to max_attempts times)
  4. Each wait is longer than the previous (backoff)
  5. If all attempts fail, raise the last exception

The "@wraps(func)" line preserves the original function's name and docstring
so that debugging still works properly.

JSON HELPERS:

    def save_json(data, filepath):

Converts a Python object to JSON and writes it to a file.
- Creates parent folders automatically (mkdir(parents=True))
- Uses indent=2 for readable output
- Uses ensure_ascii=False so non-English text is preserved

    def load_json(filepath):

Reads a JSON file and converts it back to a Python object.


================================================================================
5.  scraper.py  -  THE MAIN ENGINE
================================================================================

WHY THIS FILE EXISTS:
---------------------
This is the heart of the project. It uses Playwright to control a real
Chromium browser, visit TikTok pages, and extract data.

IMPORTS:

    import asyncio        # For async/await (running things concurrently)
    import re             # For regular expressions (pattern matching in URLs)
    from playwright.async_api import ...  # The browser automation library
    from config import CONFIG, Config
    from models import Profile, VideoDetail, VideoTile
    from utils import async_retry, get_logger, save_json

The scraper imports from the other modules we created. This is how the
pieces fit together.

URL HELPERS (simple functions, not part of the class):

    def _is_profile_url(url):
    def _is_video_url(url):
    def _extract_video_id(url):
    def _extract_username(url):

These are "private" functions (name starts with _) that help identify and
extract information from TikTok URLs.

For example, _extract_username uses a regular expression:
    re.match(r"/@([\w.]+)", parsed.path)
This finds the @username part of the URL like "/@emilyfluri"

SAFE SELECTOR HELPERS:

    async def _safe_text(page, selector, default=""):

Tries to find an element on the page and read its text. If anything goes
wrong (element not found, timeout, error), it returns the default value
instead of crashing. This is called "failing gracefully."

    async def _safe_attr(page, selector, attr, default=None):

Same as _safe_text but reads an HTML attribute instead of text.
For example, reading the "src" attribute of an <img> tag to get the
image URL.

    async def _safe_count(page, selector):

Returns how many elements match a selector.

THE MAIN CLASS: TikTokScraper

    class TikTokScraper:

This is the main class that does everything. Let's understand it piece by
piece.

CONSTRUCTOR (__init__):

    def __init__(self, config=None, captcha_wait=0):

- config: optional custom configuration (uses defaults if not provided)
- captcha_wait: how many seconds to wait for manual CAPTCHA solving

LIFECYCLE METHODS:

    async def __aenter__(self):   # Called when using "async with"
    async def __aexit__(self, ...):  # Called when exiting "async with"
    async def start(self):        # Starts the browser
    async def stop(self):         # Stops the browser

The "async with" pattern is:
    async with TikTokScraper() as scraper:
        # use scraper here
    # browser automatically closed

start() does:
1. Launches Playwright (the engine behind the scenes)
2. Launches Chromium browser with anti-detection flags
3. Creates a browser context (like an incognito window) with:
   - A realistic user agent (looks like a real Chrome browser)
   - US English locale
   - New York timezone
   - 1920x1080 screen resolution

The anti-detection flags help prevent TikTok from knowing we're a bot:
  --disable-blink-features=AutomationControlled  # Hides automation signals
  --no-sandbox                                   # Required for some systems
  --disable-web-security                         # Prevents some restrictions

PUBLIC METHODS (what the user calls):

    async def scrape_profile(self, url, save=True):

1. Extract the username from the URL
2. Create a new browser tab (page)
3. Navigate to the URL
4. If captcha_wait is set, pause so user can solve CAPTCHA
5. Dismiss any cookie banner
6. Click the "Videos" tab
7. Scroll down to load videos
8. Wait 2 seconds for everything to settle
9. Read all the profile data from the page using the safe helpers
10. Create a Profile object with all the data
11. If save=True, write the data to a JSON file
12. Close the tab
13. Return the Profile object

    async def scrape_video(self, url, save=True):

Same pattern but for a video detail page. Reads:
- Description, author, plays, likes, comments, shares, saves, sound, date

INTERNAL HELPERS (private to the class):

    async def _navigate(self, page, url):

Navigates the browser to a URL. Uses @async_retry() so if the page fails
to load, it tries again. The wait_until="domcontentloaded" means we
continue as soon as the HTML is loaded (we don't wait for images, etc.).

    async def _dismiss_cookie_banner(self, page):

TikTok shows a cookie consent banner. This tries to click "Reject" or
"Decline" to dismiss it. It tries multiple selectors in case the banner
has different text. If nothing works, it just continues (best-effort).

    async def _click_videos_tab(self, page):

TikTok profile pages have tabs: Videos, Drama, Repost, Liked.
The video grid only shows when the "Videos" tab is selected. This method
checks if the Videos tab is already active and clicks it if not.

    async def _scroll_for_content(self, page):

This is critical. TikTok loads videos only when you scroll down.
The method:
1. Scrolls down by scroll_amount pixels
2. Waits for scroll_pause milliseconds
3. Checks if the page height changed (new content loaded)
4. If height hasn't changed for 5 consecutive scrolls AND we've
   scrolled at least 5 times, we stop
5. Otherwise, continue scrolling up to max_scrolls times

The "at least 5 scrolls" rule is important because TikTok needs multiple
scroll events even when at the page bottom to trigger lazy loading.

    async def _extract_video_tiles(self, page):

After scrolling, this method reads all the video tiles from the page.
For each tile (video in the grid):
1. Find the <a> link and extract the video URL
2. Find the <img> and extract the cover image
3. Try to find the description and play count
4. Create a VideoTile object with this data

We use "tile.locator(...)" instead of "page.locator(...)" to scope
our search to just that one tile, avoiding confusion between tiles.


================================================================================
6.  main.py  -  THE ENTRY POINT
================================================================================

WHY THIS FILE EXISTS:
---------------------
This is what you run when you type "python main.py ..." in the terminal.
It parses command-line arguments, creates the scraper, and calls the
appropriate method.

ARGUMENT PARSER:

    parser.add_argument("type", choices=["profile", "video"])
    parser.add_argument("url")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--captcha-wait", type=int, default=0)

This uses argparse (Python's built-in argument parser) to handle:
- type: "profile" or "video" (required)
- url: the TikTok URL (required)
- --no-save: print to screen instead of saving to file
- --headless: run browser invisibly (default)
- --visible: show the browser window
- --captcha-wait: seconds to wait for manual CAPTCHA solving

THE MAIN FUNCTION (_amain):

    async def _amain():

1. Parse the command-line arguments
2. Determine if we should run headless or visible
3. Create a TikTokScraper instance (passing captcha_wait)
4. Start the browser
5. Call scrape_profile or scrape_video based on the type argument
6. If --no-save, print the result as JSON
7. If anything fails, log the error and exit with status 1
8. Always stop the browser (finally block)

    def main():
        asyncio.run(_amain())

This is the synchronous entry point. Python's asyncio.run() creates an
event loop and runs the async function.

    if __name__ == "__main__":
        main()

This runs main() only when you execute the file directly (not when you
import it from another file).


================================================================================
7.  HOW EVERYTHING FITS TOGETHER (FLOW DIAGRAM)
================================================================================

You run:  python main.py profile https://www.tiktok.com/@someone --visible

1. main.py parses arguments
2. main.py creates TikTokScraper  (from scraper.py)
3. TikTokScraper.start():
   - Launches Chromium browser
   - Creates browsing context
4. TikTokScraper.scrape_profile(url):
   a. Opens new page (browser tab)
   b. Navigates to the URL (config.py controls timeouts)
   c. Waits for CAPTCHA if --captcha-wait was used
   d. Dismisses cookie banner
   e. Clicks "Videos" tab
   f. Scrolls to trigger lazy loading
   g. Reads page data using selectors (from config.py)
   h. Creates Profile object (from models.py)
   i. Saves Profile as JSON (from utils.py)
   j. Returns Profile
5. main.py prints or saves the result
6. TikTokScraper.stop() closes the browser


================================================================================
8.  HOW TO RUN THE PROJECT
================================================================================

FIRST TIME SETUP:
-----------------
  1. Install dependencies:
     pip install -r requirements.txt

  2. Install Playwright browser:
     python -m playwright install chromium

SCRAPE A PROFILE:
-----------------
  python main.py profile https://www.tiktok.com/@username

  This runs headless (invisible). You'll see log output in the terminal.
  Results save to:  output/profile_username.json

SCRAPE A VIDEO:
---------------
  python main.py video https://www.tiktok.com/@username/video/1234567890

WITH VISIBLE BROWSER:
--------------------
  python main.py profile https://www.tiktok.com/@username --visible

  Useful for debugging. You'll see the browser open and navigate.

WITH CAPTCHA WAIT:
-----------------
  python main.py profile https://www.tiktok.com/@username --visible --captcha-wait 15

  Opens the browser. If TikTok shows a CAPTCHA, you have 15 seconds to
  solve it manually. Then the scraper continues automatically.

PRINT TO SCREEN INSTEAD OF SAVING:
----------------------------------
  python main.py profile https://www.tiktok.com/@username --no-save


================================================================================
9.  TROUBLESHOOTING TIPS
================================================================================

PROBLEM: "ModuleNotFoundError: No module named 'playwright'"
SOLUTION: Run:  pip install playwright

PROBLEM: "Executable doesn't exist at ..."
SOLUTION: Run:  python -m playwright install chromium

PROBLEM: TikTok shows a blank page or CAPTCHA
SOLUTION: Use --visible and --captcha-wait 15 to solve it manually

PROBLEM: No videos found in the output
SOLUTION: TikTok's page structure may have changed. Update the selectors
          in config.py by inspecting TikTok's HTML.

PROBLEM: The browser opens but nothing happens
SOLUTION: Check your internet connection. TikTok may be blocked in your
          region or require a VPN.

================================================================================
                           END OF GUIDE
================================================================================
