"""
Playwright-based TikTok scraper.

Extracts structured data from TikTok's embedded ``__UNIVERSAL_DATA_FOR_REHYDRATION__``
JSON (stable across frontend changes) and falls back to DOM scraping only
for dynamically loaded content (comments and profile video tiles).
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
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
from utils import get_logger, save_json

logger = get_logger(__name__)

_TIKTOK_DOMAINS = {"tiktok.com", "www.tiktok.com"}


def _extract_video_id(url: str) -> str:
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else ""


def _extract_username(url: str) -> str:
    parsed = urlparse(url)
    match = re.match(r"/@([\w.]+)", parsed.path)
    return match.group(1) if match else ""


_SEL = CONFIG.selectors


class TikTokScraper:
    """
    High-level TikTok scraper built on Playwright and embedded JSON data.
    """

    def __init__(self, config: Config | None = None, captcha_wait: int = 0) -> None:
        self._config = config or CONFIG
        self._captcha_wait = captcha_wait
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> "TikTokScraper":
        await self.start()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.stop()

    async def start(self) -> None:
        """Initialise Playwright, launch the browser, and create a persistent context."""
        logger.info("Starting TikTokScraper …")
        self._playwright = await async_playwright().start()

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
    # Embedded JSON extraction
    # ------------------------------------------------------------------

    async def _extract_embedded_json(self, page: Page) -> dict:
        data = await page.evaluate("""() => {
            const el = document.getElementById("__UNIVERSAL_DATA_FOR_REHYDRATION__");
            if (!el) return null;
            try { return JSON.parse(el.innerText); }
            catch { return null; }
        }""")
        if not data:
            logger.warning("Could not find __UNIVERSAL_DATA_FOR_REHYDRATION__ in page.")
            return {}
        return data.get("__DEFAULT_SCOPE__", {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape_profile(self, url: str, save: bool = True) -> Profile:
        username = _extract_username(url)
        logger.info("Scraping profile: %s", url)

        page = await self._context.new_page()
        try:
            await self._navigate(page, url)
            if self._captcha_wait:
                logger.info("Waiting %d s for manual CAPTCHA solving …", self._captcha_wait)
                await page.wait_for_timeout(self._captcha_wait * 1000)
            await self._dismiss_cookie_banner(page)

            scope = await self._extract_embedded_json(page)
            user_data = scope.get("webapp.user-detail", {})
            user_info = user_data.get("userInfo", {})
            user = user_info.get("user", {})
            stats = user_info.get("stats", {})

            await self._click_videos_tab(page)
            await self._scroll_for_content(page)
            await page.wait_for_timeout(2000)

            recent_videos = await self._extract_video_tiles(page)

            profile = Profile(
                url=url,
                username=username,
                nickname=user.get("nickname", ""),
                avatar=user.get("avatarLarger") or user.get("avatarMedium") or user.get("avatarThumb"),
                bio=user.get("signature", ""),
                follower_count=str(stats.get("followerCount", "")),
                following_count=str(stats.get("followingCount", "")),
                like_count=str(stats.get("heartCount", "") or stats.get("heart", "")),
                video_count=str(stats.get("videoCount", "")),
                recent_videos=recent_videos,
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

    async def scrape_video(
        self, url: str, save: bool = True,
        like: bool = False, comment: str = "",
    ) -> VideoDetail:
        video_id = _extract_video_id(url)
        logger.info("Scraping video: %s", url)

        page = await self._context.new_page()
        try:
            await self._navigate(page, url)
            if self._captcha_wait:
                logger.info("Waiting %d s for manual CAPTCHA solving …", self._captcha_wait)
                await page.wait_for_timeout(self._captcha_wait * 1000)
            await self._dismiss_cookie_banner(page)

            scope = await self._extract_embedded_json(page)
            video_data = scope.get("webapp.video-detail", {})
            item = video_data.get("itemInfo", {}).get("itemStruct", {})
            stats = item.get("stats", {})
            author = item.get("author", {})
            music = item.get("music", {})

            plays = str(stats.get("playCount", ""))
            likes = str(stats.get("diggCount", ""))
            comments_count = str(stats.get("commentCount", ""))
            shares = str(stats.get("shareCount", ""))
            saves = str(stats.get("collectCount", ""))

            author_id = author.get("uniqueId", "")
            author_avatar = author.get("avatarLarger") or author.get("avatarMedium") or author.get("avatarThumb")

            sound_title = music.get("title", "")
            sound_author = music.get("authorName", "")
            sound = f"{sound_title} - {sound_author}" if sound_title and sound_author else (sound_title or sound_author or "")

            create_time = item.get("createTime", "")
            if create_time:
                try:
                    date_str = datetime.utcfromtimestamp(int(create_time)).strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    date_str = str(create_time)
            else:
                date_str = ""

            description = item.get("desc", "")

            if like:
                await self._like_video(page)

            comments_data = await self._extract_comments(page, video_id)

            if comment:
                # Try to open panel and post comment even if extraction failed
                await self._open_comments_panel(page)
                await self._comment_on_video(page, comment)

            video = VideoDetail(
                url=url,
                id=video_id,
                description=description,
                author_username=author_id,
                author_avatar=author_avatar,
                plays=plays,
                likes=likes,
                comments=comments_count,
                shares=shares,
                saves=saves,
                sound=sound,
                date=date_str,
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

    @staticmethod
    async def _navigate(page: Page, url: str) -> None:
        logger.debug("Navigating to %s", url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=CONFIG.timeout.page_load)
        except PlaywrightTimeout:
            logger.warning("Page load timeout for %s – continuing with partial DOM.", url)

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        dismiss_selectors = [
            _SEL.cookie_reject,
            _SEL.cookie_decline,
            _SEL.cookie_accept,
            _SEL.cookie_banner_btn,
        ]
        for sel in dismiss_selectors:
            try:
                btn = await page.wait_for_selector(sel, timeout=3_000)
                if btn:
                    await btn.click()
                    logger.debug("Cookie banner dismissed via '%s'.", sel)
                    await asyncio.sleep(0.5)
                return
            except (PlaywrightTimeout, Exception):
                continue

    async def _click_videos_tab(self, page: Page) -> None:
        if not _SEL.videos_tab:
            return
        try:
            tab = await page.wait_for_selector(_SEL.videos_tab, timeout=CONFIG.timeout.element_appear)
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

            if i >= 4 and consecutive_same_height >= 5:
                logger.debug("Scroll finished after %d steps.", i + 1)
                break

            prev_height = new_height
        else:
            logger.debug("Reached max scrolls.", self._config.scroll.max_scrolls)

    async def _extract_video_tiles(self, page: Page) -> list:
        tiles = page.locator(_SEL.video_tiles)
        count = await tiles.count()
        logger.debug("Found %d video tiles.", count)
        results: list = []
        for i in range(count):
            tile = tiles.nth(i)
            try:
                link_el = tile.locator(_SEL.video_tile_link).first
                href = await link_el.get_attribute("href") or ""
                full_url = (
                    f"https://www.tiktok.com{href}"
                    if href.startswith("/")
                    else href
                )

                cover = tile.locator(_SEL.video_tile_cover).first
                cover_src = await cover.get_attribute("src")

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

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    async def _open_comments_panel(self, page: Page) -> bool:
        """
        Try to open the comments panel by clicking various selectors.

        Returns True if the panel was likely opened.
        """
        click_selectors = [
            _SEL.comment_open_icon,
            _SEL.comment_input,
            '[data-e2e="comment-count"]',
            '[data-e2e="comment-icon"]',
            'button:has([data-e2e*="comment" i])',
        ]

        for sel in click_selectors:
            if not sel:
                continue
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.scroll_into_view_if_needed()
                    await page.wait_for_timeout(300)
                    await btn.click(force=True)
                    logger.debug("Opened comments via '%s'.", sel)
                    await page.wait_for_timeout(4000)
                    return True
            except Exception:
                continue

        logger.debug("Could not find any comment button to click.")
        return False

    async def _scrape_comment_dom(self, page: Page) -> list:
        """Extract comments from rendered DOM after panel is open."""
        results: list = []
        wrappers = page.locator(_SEL.comment_wrapper)
        count = await wrappers.count()
        logger.debug("Found %d comment wrappers in DOM.", count)

        for i in range(count):
            try:
                wrapper = wrappers.nth(i)

                author = ""
                author_el = wrapper.locator(_SEL.comment_author).first
                if await author_el.count():
                    author = (await author_el.inner_text()).strip()

                avatar = None
                avatar_el = wrapper.locator(_SEL.comment_author_avatar).first
                if await avatar_el.count():
                    avatar = await avatar_el.get_attribute("src")

                text = ""
                text_el = wrapper.locator(_SEL.comment_text).first
                if await text_el.count():
                    text = (await text_el.inner_text()).strip()

                if text:
                    results.append(Comment(author_username=author, author_avatar=avatar, text=text))
            except Exception as exc:
                logger.debug("Skipping comment wrapper %d: %s", i, exc)
                continue

        return results

    async def _fetch_comments_api(self, page: Page, video_id: str) -> list:
        """
        Fallback: call the TikTok comment API from the browser context
        (uses the page's cookies and CSRF tokens).
        """
        try:
            data = await page.evaluate(f"""async () => {{
                try {{
                    const r = await fetch(
                        "https://www.tiktok.com/api/comment/list/?aweme_id={video_id}&count=50&cursor=0",
                        {{ credentials: "include", headers: {{ "Referer": "https://www.tiktok.com/" }} }}
                    );
                    const d = await r.json();
                    if (d.status_code !== 0) return {{ error: "status_code " + d.status_code }};
                    return d;
                }} catch(e) {{ return {{ error: e.toString() }}; }}
            }}""")

            if "error" in data:
                logger.debug("Comment API fallback failed: %s", data["error"])
                return []

            comments_data = data.get("comments", [])
            if not comments_data:
                logger.debug("Comment API returned no comments.")
                return []

            logger.debug("Fetched %d comments via API.", len(comments_data))
            results = []
            for c in comments_data:
                user = c.get("user", {}) or {}
                results.append(Comment(
                    author_username=user.get("uniqueId", "") or user.get("nickname", ""),
                    author_avatar=user.get("avatarLarger") or user.get("avatarThumb"),
                    text=c.get("text", ""),
                    likes=str(c.get("diggCount", c.get("likes", ""))),
                    replies_count=str(c.get("replyCount", c.get("reply_comment_total", ""))),
                ))
            return results

        except Exception as exc:
            logger.debug("Comment API fallback threw: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    async def _like_video(self, page: Page) -> None:
        try:
            btn = page.locator(_SEL.like_button).first
            if await btn.count() == 0:
                logger.debug("Like button not found.")
                return
            pressed = await btn.get_attribute("aria-pressed")
            if pressed == "true":
                logger.info("Video already liked, skipping.")
                return
            await btn.scroll_into_view_if_needed()
            await btn.click(force=True)
            logger.info("Video liked.")
            await page.wait_for_timeout(1500)
        except Exception as exc:
            logger.warning("Failed to like video: %s", exc)

    async def _comment_on_video(self, page: Page, text: str) -> None:
        try:
            input_el = page.locator(_SEL.comment_input).first
            if await input_el.count() == 0:
                logger.debug("Comment input not found.")
                return
            await input_el.scroll_into_view_if_needed()
            await input_el.click()
            await page.wait_for_timeout(500)

            await page.keyboard.type(text, delay=50)
            logger.debug("Typed comment text.")
            await page.wait_for_timeout(500)

            post_btn = page.locator(_SEL.comment_post_button).first
            if await post_btn.count() > 0:
                await post_btn.click()
                logger.info("Comment posted.")
                await page.wait_for_timeout(2000)
            else:
                await input_el.press("Enter")
                logger.info("Comment posted via Enter.")
                await page.wait_for_timeout(2000)
        except Exception as exc:
            logger.warning("Failed to post comment: %s", exc)

    async def _extract_comments(self, page: Page, video_id: str) -> list:
        """
        Extract comments from the video page.

        Tries multiple strategies in order:
          1. Click the comment button and scrape the rendered DOM
          2. Fetch comments via TikTok API using the page context
        """
        # Strategy 1: open comment panel and scrape DOM
        panel_opened = await self._open_comments_panel(page)
        if panel_opened:
            dom_comments = await self._scrape_comment_dom(page)
            if dom_comments:
                return dom_comments

        # Strategy 2: try API fetch from page context
        logger.debug("DOM comment extraction failed, trying API fallback …")
        api_comments = await self._fetch_comments_api(page, video_id)
        if api_comments:
            return api_comments

        return []
