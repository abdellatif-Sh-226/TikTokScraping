"""
Configuration module for the TikTok scraper.

Centralises all configurable settings such as selectors, timeouts,
retry policies, and file paths. Keeps hardcoded values out of the
business-logic modules.
"""

from dataclasses import dataclass, field
from typing import Dict


# ---------------------------------------------------------------------------
# Timeouts & delays
# ---------------------------------------------------------------------------

@dataclass
class TimeoutConfig:
    """Timeout values used throughout the scraper (milliseconds)."""
    page_load: int = 15_000
    """Maximum wait for a page to load."""
    element_appear: int = 10_000
    """Maximum wait for a single element to appear."""
    scroll_pause: int = 2_000
    """Pause (ms) between scroll steps to let content render."""
    retry_delay: int = 2_000
    """Base delay (ms) between retry attempts."""


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    """Retry behaviour on transient failures."""
    max_attempts: int = 3
    """How many times to retry a failing operation."""
    backoff_factor: float = 1.5
    """Multiplier applied to delay after each retry."""


# ---------------------------------------------------------------------------
# Scrolling
# ---------------------------------------------------------------------------

@dataclass
class ScrollConfig:
    """Behaviour for infinite-scroll pagination."""
    max_scrolls: int = 20
    """Maximum number of scroll-down actions."""
    scroll_amount: int = 1000
    """Pixel distance per scroll."""


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------

@dataclass
class OutputConfig:
    """Where and how scraped data is saved."""
    output_dir: str = "output"
    """Directory for JSON result files."""
    profile_filename: str = "profile_{username}.json"
    video_filename: str = "video_{id}.json"
    """Filename templates.  Use ``{username}`` / ``{id}`` placeholders."""


# ---------------------------------------------------------------------------
# Selectors  (centralised so they can be updated without touching logic)
# ---------------------------------------------------------------------------

@dataclass
class Selectors:
    """
    CSS / XPath selectors for TikTok page elements.

    TikTok frequently changes its markup, so keeping them here makes
    maintenance significantly easier.
    """

    # --- Profile page ---
    profile_wrapper: str = '[data-e2e="user-page"]'
    username: str = '[data-e2e="user-title"]'
    nickname: str = '[data-e2e="user-subtitle"]'
    avatar: str = '[data-e2e="user-avatar"] img'
    bio: str = '[data-e2e="user-bio"]'
    follower_count: str = '[data-e2e="followers-count"]'
    following_count: str = '[data-e2e="following-count"]'
    like_count: str = '[data-e2e="likes-count"]'
    video_count: str = ''
    videos_tab: str = '[data-e2e="videos-tab"]'

    # --- Video tiles (profile page grid) ---
    video_tiles: str = '[data-e2e="user-post-item"]'
    video_tile_link: str = 'a'
    video_tile_cover: str = 'img'
    video_tile_plays: str = '[data-e2e="video-views"]'
    video_tile_desc: str = '[data-e2e="video-title"]'

    # --- Video detail page ---
    video_wrapper: str = '[data-e2e="video-detail"]'
    video_desc: str = '[data-e2e="video-desc"]'
    video_author: str = '[data-e2e="video-author-uniqueid"]'
    video_author_avatar: str = '[data-e2e="video-author-avatar"] img'
    video_plays: str = '[data-e2e="video-views"]'
    video_likes: str = '[data-e2e="like-count"]'
    video_comments: str = '[data-e2e="comment-count"]'
    video_shares: str = '[data-e2e="share-count"]'
    video_saves: str = '[data-e2e="bookmark-count"]'
    video_sound: str = '[data-e2e="video-music"]'
    video_date: str = '[data-e2e="video-date"]'
    video_comments_section: str = '[data-e2e="comments-list"]'

    # --- Comments ---
    comment_open_icon: str = '[data-e2e="comment-icon"]'
    """Button/icon to click to open the comments panel."""
    comment_wrapper: str = 'div[class*="DivCommentItemWrapper"]'
    """Full wrapper div around a single comment."""
    comment_author: str = 'p.TUXText--weight-medium'
    """Username text element inside a comment wrapper."""
    comment_author_avatar: str = 'img'
    """Avatar image inside a comment wrapper."""
    comment_text: str = 'span.TUXText--weight-normal'
    """Comment body text element."""

    # --- Cookie banner ---
    cookie_reject: str = 'button:has-text("Reject")'
    """'Reject all' button on the cookie consent banner."""
    cookie_decline: str = 'button:has-text("Decline")'
    """'Decline' button on the cookie consent banner."""
    cookie_accept: str = 'button:has-text("Accept")'
    """'Accept all' button (fallback if Reject/Decline absent)."""
    cookie_banner_btn: str = '[data-e2e="cookie-banner"] button'
    """Generic cookie banner button fallback."""

    # --- Generic ---
    error_page: str = 'div.error_container'


# ---------------------------------------------------------------------------
# Master configuration
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """Aggregate configuration object."""
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    selectors: Selectors = field(default_factory=Selectors)

    browser_headless: bool = False
    """Run Playwright in headless mode."""
    storage_state_file: str = "tiktok_session.json"
    """File to save/restore browser session (cookies, localStorage)."""


# Singleton-style convenience instance
CONFIG = Config()
