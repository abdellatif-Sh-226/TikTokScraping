"""
Playwright-based TikTok scraper.

Provides the ``TikTokScraper`` class which can extract:
- Profile information (bio, stats, avatar, recent video tiles).
- Video detail information (description, engagement stats, sound, upload date).

Uses a persistent browser context for session reuse and implements
automatic scrolling, retry logic, and centralised selector management.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from config import CONFIG, Config
from models import Comment, Profile, VideoDetail, VideoTile
from utils import async_retry, get_logger, save_json

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

_TIKTOK_DOMAINS = {"tiktok.com", "www.tiktok.com"}


def _is_profile_url(url: str) -> bool:
    """Return ``True`` if *url* looks like a TikTok profile page."""
    parsed = urlparse(url)
    if parsed.netloc not in _TIKTOK_DOMAINS:
        return False
    # Profile URLs: /@username  or  /@username/
    return bool(re.match(r"/@[\w.]+", parsed.path))


def _is_video_url(url: str) -> bool:
    """Return ``True`` if *url* looks like a TikTok video detail page."""
    parsed = urlparse(url)
    if parsed.netloc not in _TIKTOK_DOMAINS:
        return False
    # Video URLs: /@username/video/1234567890  or  /video/1234567890
    return bool(re.search(r"/video/\d+", parsed.path))


def _extract_video_id(url: str) -> str:
    """Extract the numeric video ID from a TikTok video URL."""
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else ""


def _extract_username(url: str) -> str:
    """Extract the @username from a TikTok profile URL."""
    parsed = urlparse(url)
    match = re.match(r"/@([\w.]+)", parsed.path)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Selector helpers
# ---------------------------------------------------------------------------

_SEL = CONFIG.selectors


async def _safe_text(page: Page, selector: str, default: str = "") -> str:
    """
    Return the ``.inner_text()`` of *selector*, or *default* if missing.

    Never raises – all exceptions are caught and result in the default.
    """
    if not selector:
        return default
    try:
        el = await page.wait_for_selector(selector, timeout=CONFIG.timeout.element_appear)
        if el:
            return (await el.inner_text()).strip()
    except (PlaywrightTimeout, AttributeError):
        pass
    return default


async def _safe_attr(page: Page, selector: str, attr: str, default: Optional[str] = None) -> Optional[str]:
    """Return an attribute value from *selector*, or *default* if missing."""
    if not selector:
        return default
    try:
        el = await page.wait_for_selector(selector, timeout=CONFIG.timeout.element_appear)
        if el:
            return await el.get_attribute(attr)
    except (PlaywrightTimeout, AttributeError):
        pass
    return default


async def _safe_count(page: Page, selector: str) -> int:
    """Return the number of elements matching *selector*."""
    return await page.locator(selector).count()


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------


class TikTokScraper:
    """
    High-level TikTok scraper built on Playwright.

    Usage::

        async with TikTokScraper() as scraper:
            profile = await scraper.scrape_profile("https://www.tiktok.com/@username")
            video   = await scraper.scrape_video("https://www.tiktok.com/@username/video/1234567890")

    The scraper uses a **persistent browser context** (cookies, local storage)
    stored in ``Config.user_data_dir``, so subsequent runs benefit from
    cached sessions and are less likely to be rate-limited.
    """

    def __init__(self, config: Config | None = None, captcha_wait: int = 0) -> None:
        self._config = config or CONFIG
        self._captcha_wait = captcha_wait
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "TikTokScraper":
        await self.start()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.stop()

    async def start(self) -> None:
        """Initialise Playwright, launch the browser, and create a persistent context."""
        logger.info("Starting TikTokScraper …")
        self._playwright = await async_playwright().start()

        # Anti-detection launch args to bypass headless blocking
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        self._browser = await self._playwright.chromium.launch(
            headless=self._config.browser_headless,
            args=launch_args,
        )

        # Load saved session (cookies + localStorage) if available
        storage_state = None
        state_path = Path(self._config.storage_state_file)
        if state_path.exists():
            try:
                storage_state = json.loads(state_path.read_text(encoding="utf-8"))
                logger.info("Loaded saved session from %s", state_path)
            except Exception as exc:
                logger.warning("Failed to load saved session: %s", exc)

        self._context = await self._browser.new_context(
            storage_state=storage_state,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            viewport={"width": 1920, "height": 1080},
        )

        logger.info("Browser context created.")

    async def stop(self) -> None:
        """Save session, close the browser and stop Playwright."""
        await self._save_session()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("TikTokScraper stopped.")

    async def _save_session(self) -> None:
        """Persist the current browser session (cookies + localStorage) to disk."""
        if not self._context:
            return
        try:
            state = await self._context.storage_state()
            state_path = Path(self._config.storage_state_file)
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            logger.info("Session saved to %s", state_path)
        except Exception as exc:
            logger.warning("Failed to save session: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape_profile(self, url: str, save: bool = True) -> Profile:
        """
        Scrape a TikTok profile page and return a ``Profile`` instance.

        Parameters
        ----------
        url:
            Full profile URL, e.g. ``https://www.tiktok.com/@username``.
        save:
            If ``True`` (default), write the result to a JSON file.
        """
        username = _extract_username(url)
        logger.info("Scraping profile: %s", url)

        page = await self._context.new_page()  # type: ignore[union-attr]
        try:
            await self._navigate(page, url)
            # If --captcha-wait was given, pause here for manual solving
            if self._captcha_wait:
                logger.info("Waiting %d s for manual CAPTCHA solving …", self._captcha_wait)
                await page.wait_for_timeout(self._captcha_wait * 1000)
            await self._dismiss_cookie_banner(page)
            await self._click_videos_tab(page)
            await self._scroll_for_content(page)
            await page.wait_for_timeout(2000)

            profile = Profile(
                url=url,
                username=username,
                nickname=await _safe_text(page, _SEL.nickname),
                avatar=await _safe_attr(page, _SEL.avatar, "src"),
                bio=await _safe_text(page, _SEL.bio),
                follower_count=await _safe_text(page, _SEL.follower_count),
                following_count=await _safe_text(page, _SEL.following_count),
                like_count=await _safe_text(page, _SEL.like_count),
                video_count=await _safe_text(page, _SEL.video_count),
                recent_videos=await self._extract_video_tiles(page),
            )

            logger.info(
                "Profile scraped: @%s — %s followers, %d video tiles.",
                profile.username,
                profile.follower_count,
                len(profile.recent_videos),
            )

            if save:
                fname = self._config.output.profile_filename.format(username=username)
                save_json(profile.model_dump(), f"{self._config.output.output_dir}/{fname}")

            return profile
        finally:
            await page.close()

    async def scrape_video(self, url: str, save: bool = True) -> VideoDetail:
        """
        Scrape a TikTok video detail page and return a ``VideoDetail`` instance.

        Parameters
        ----------
        url:
            Full video URL, e.g.
            ``https://www.tiktok.com/@username/video/1234567890``.
        save:
            If ``True`` (default), write the result to a JSON file.
        """
        video_id = _extract_video_id(url)
        logger.info("Scraping video: %s", url)

        page = await self._context.new_page()  # type: ignore[union-attr]
        try:
            await self._navigate(page, url)
            # If --captcha-wait was given, pause here for manual solving
            if self._captcha_wait:
                logger.info("Waiting %d s for manual CAPTCHA solving …", self._captcha_wait)
                await page.wait_for_timeout(self._captcha_wait * 1000)
            await self._dismiss_cookie_banner(page)

            # Click the comment button to open the comment panel
            await self._open_comments_panel(page)
            comments_data = await self._extract_comments(page)

            video = VideoDetail(
                url=url,
                id=video_id,
                description=await _safe_text(page, _SEL.video_desc),
                author_username=await _safe_text(page, _SEL.video_author),
                author_avatar=await _safe_attr(page, _SEL.video_author_avatar, "src"),
                plays=await _safe_text(page, _SEL.video_plays),
                likes=await _safe_text(page, _SEL.video_likes),
                comments=await _safe_text(page, _SEL.video_comments),
                shares=await _safe_text(page, _SEL.video_shares),
                saves=await _safe_text(page, _SEL.video_saves),
                sound=await _safe_text(page, _SEL.video_sound),
                date=await _safe_text(page, _SEL.video_date),
                comments_list=comments_data,
            )

            logger.info(
                "Video scraped: %s — %s plays, %s likes, %d comments.",
                video.id,
                video.plays,
                video.likes,
                len(comments_data),
            )

            if save:
                fname = self._config.output.video_filename.format(id=video_id)
                save_json(video.model_dump(), f"{self._config.output.output_dir}/{fname}")

            return video
        finally:
            await page.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @async_retry()
    async def _navigate(self, page: Page, url: str) -> None:
        """
        Navigate to *url* and wait for the page to reach a loadable state.

        Raises ``PlaywrightTimeout`` if the page does not load within
        ``Config.timeout.page_load`` milliseconds.
        """
        logger.debug("Navigating to %s", url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=CONFIG.timeout.page_load)
        except PlaywrightTimeout:
            logger.warning("Page load timeout for %s – continuing with partial DOM.", url)

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        """
        Try to detect and dismiss the TikTok cookie consent banner.

        This is a best-effort step – failure is non-fatal.
        """
        dismiss_selectors = [
            'button:has-text("Reject")',
            'button:has-text("Decline")',
            'button:has-text("Accept")',  # Only click Accept if Reject is absent
            '[data-e2e="cookie-banner"] button',
        ]
        for sel in dismiss_selectors:
            try:
                btn = await page.wait_for_selector(sel, timeout=3_000)
                if btn:
                    await btn.click()
                    logger.debug("Cookie banner dismissed via '%s'.", sel)
                    # Short pause so the banner animation completes
                    await asyncio.sleep(0.5)
                return
            except (PlaywrightTimeout, Exception):
                continue

    async def _click_videos_tab(self, page: Page) -> None:
        """
        Click the "Videos" tab on a profile page to ensure the video
        grid is active before scrolling.

        TikTok profiles may have multiple tabs (Videos, Drama, Repost,
        Liked). The video grid only loads when the Videos tab is selected.
        """
        tab_selector = _SEL.videos_tab
        if not tab_selector:
            return
        try:
            tab = await page.wait_for_selector(tab_selector, timeout=CONFIG.timeout.element_appear)
            if tab:
                is_active = await tab.get_attribute("aria-selected")
                if is_active != "true":
                    await tab.click()
                    logger.debug("Clicked 'Videos' tab.")
                    await asyncio.sleep(1)
                else:
                    logger.debug("Videos tab already active.")
        except (PlaywrightTimeout, Exception):
            logger.debug("Videos tab not found or not clickable.")

    async def _scroll_for_content(self, page: Page) -> None:
        """
        Scroll the page down repeatedly to trigger lazy-loading.

        TikTok's profile page loads the video grid only after the user
        scrolls near the bottom. This method scrolls repeatedly and only
        stops when the page *stays* the same height for several
        consecutive attempts while at the bottom of the page.
        """
        stalled_count = 0
        consecutive_same_height = 0
        prev_height = 0

        for i in range(self._config.scroll.max_scrolls):
            await page.evaluate(f"window.scrollBy(0, {self._config.scroll.scroll_amount})")
            await asyncio.sleep(self._config.timeout.scroll_pause / 1000)

            new_height = await page.evaluate("document.documentElement.scrollHeight")

            if new_height == prev_height:
                consecutive_same_height += 1
            else:
                consecutive_same_height = 0

            # Stop only after at least 5 scrolls AND same height for
            # 5 consecutive attempts. TikTok requires multiple scroll
            # events even when at the page bottom to trigger lazy loading.
            if i >= 4 and consecutive_same_height >= 5:
                logger.debug("Scroll finished after %d steps.", i + 1)
                break

            prev_height = new_height
        else:
            logger.debug("Reached max scrolls.", self._config.scroll.max_scrolls)

    async def _extract_video_tiles(self, page: Page) -> list:
        """
        Extract video tile metadata from the profile-page video grid.

        Uses Locator methods (scoped to each tile) to avoid
        cross-contamination between tiles.
        Returns a list of ``VideoTile`` instances.
        """
        tiles = page.locator(_SEL.video_tiles)
        count = await tiles.count()
        logger.debug("Found %d video tiles.", count)
        results: list = []
        for i in range(count):
            tile = tiles.nth(i)
            try:
                # Extract URL from the <a> inside the tile
                link_el = tile.locator(_SEL.video_tile_link).first
                href = await link_el.get_attribute("href") or ""
                full_url = (
                    f"https://www.tiktok.com{href}"
                    if href.startswith("/")
                    else href
                )

                # Extract cover image
                cover = tile.locator(_SEL.video_tile_cover).first
                cover_src = await cover.get_attribute("src")

                # Extract description and plays — scoped to this tile
                desc = ""
                if _SEL.video_tile_desc:
                    desc_el = tile.locator(_SEL.video_tile_desc).first
                    if await desc_el.count():
                        desc = (await desc_el.inner_text()).strip()

                plays = ""
                if _SEL.video_tile_plays:
                    plays_el = tile.locator(_SEL.video_tile_plays).first
                    if await plays_el.count():
                        plays = (await plays_el.inner_text()).strip()

                results.append(
                    VideoTile(
                        url=full_url,
                        cover_image=cover_src,
                        description=desc,
                        plays=plays,
                    )
                )
            except Exception as exc:
                logger.debug("Skipping video tile %d due to: %s", i, exc)
                continue
        return results

    async def _open_comments_panel(self, page: Page) -> None:
        """
        Click the comment button to open the comments sidebar/panel.

        On TikTok video pages, comments are NOT in the initial DOM.
        Clicking the comment count or icon opens a side panel that loads
        comments via API. This method clicks that button and waits.
        """
        for sel in ['[data-e2e="comment-count"]', '[data-e2e="comment-icon"]']:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click()
                    logger.debug("Opened comments via '%s'.", sel)
                    await page.wait_for_timeout(3000)
                    return
            except Exception:
                continue
        logger.debug("Could not find comment button to click.")

    async def _extract_comments(self, page: Page) -> list:
        """
        Extract comments from the page after the comment panel has opened.

        Iterates over each comment wrapper div and extracts:
        - author username (from p.TUXText--weight-medium)
        - author avatar (from img)
        - comment text (from span.TUXText--weight-normal)
        """
        results: list = []

        wrappers = page.locator(_SEL.comment_wrapper)
        count = await wrappers.count()
        logger.debug("Found %d comment wrappers.", count)

        for i in range(count):
            try:
                wrapper = wrappers.nth(i)

                # Author username
                author = ""
                author_el = wrapper.locator(_SEL.comment_author).first
                if await author_el.count():
                    author = (await author_el.inner_text()).strip()

                # Author avatar
                avatar = None
                avatar_el = wrapper.locator(_SEL.comment_author_avatar).first
                if await avatar_el.count():
                    avatar = await avatar_el.get_attribute("src")

                # Comment text
                text = ""
                text_el = wrapper.locator(_SEL.comment_text).first
                if await text_el.count():
                    text = (await text_el.inner_text()).strip()

                if text:
                    results.append(
                        Comment(
                            author_username=author,
                            author_avatar=avatar,
                            text=text,
                        )
                    )
            except Exception as exc:
                logger.debug("Skipping comment wrapper %d: %s", i, exc)
                continue

        return results
