"""
Configuration module for the TikTok scraper.

Centralises all configurable settings such as selectors, timeouts,
retry policies, and file paths. Keeps hardcoded values out of the
business-logic modules.
"""

from dataclasses import dataclass, field


@dataclass
class TimeoutConfig:
    page_load: int = 15_000
    element_appear: int = 10_000
    scroll_pause: int = 2_000
    retry_delay: int = 2_000


@dataclass
class RetryConfig:
    max_attempts: int = 3
    backoff_factor: float = 1.5


@dataclass
class ScrollConfig:
    max_scrolls: int = 20
    scroll_amount: int = 1000


@dataclass
class OutputConfig:
    output_dir: str = "output"
    profile_filename: str = "profile_{username}.json"
    video_filename: str = "video_{id}.json"


@dataclass
class Selectors:
    """
    CSS / XPath selectors for elements that are NOT covered by the
    embedded JSON (__UNIVERSAL_DATA_FOR_REHYDRATION__).
    """
    # --- Profile page ---
    videos_tab: str = '[data-e2e="videos-tab"]'

    # --- Video tiles (profile page grid — loaded dynamically) ---
    video_tiles: str = '[data-e2e="user-post-item"]'
    video_tile_link: str = 'a'
    video_tile_cover: str = 'img'
    video_tile_plays: str = '[data-e2e="video-views"]'
    video_tile_desc: str = '[data-e2e="video-title"]'

    # --- Actions (like, comment) ---
    like_button: str = '[data-e2e="like-count"]'
    comment_input: str = '[data-e2e="comment-input"]'
    comment_post_button: str = 'button[data-e2e="comment-post"]'

    # --- Comments (loaded dynamically via API, not in initial JSON) ---
    comment_open_icon: str = '[data-e2e="comment-icon"]'
    comment_wrapper: str = 'div[class*="DivCommentItemWrapper"]'
    comment_author: str = 'p.TUXText--weight-medium'
    comment_author_avatar: str = 'img'
    comment_text: str = 'span.TUXText--weight-normal'

    # --- Cookie banner ---
    cookie_reject: str = 'button:has-text("Reject")'
    cookie_decline: str = 'button:has-text("Decline")'
    cookie_accept: str = 'button:has-text("Accept")'
    cookie_banner_btn: str = '[data-e2e="cookie-banner"] button'


@dataclass
class Config:
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    selectors: Selectors = field(default_factory=Selectors)

    browser_headless: bool = False
    storage_state_file: str = "tiktok_session.json"


CONFIG = Config()
