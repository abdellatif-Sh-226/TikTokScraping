"""
Data models for TikTok scraped entities.

Uses Pydantic for validation, serialisation, and clean JSON export.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class VideoTile(BaseModel):
    """
    Minimal video info extracted from a profile-page grid tile.

    This is less detailed than the data obtained from a dedicated video
    detail page, but is useful for building an overview of a user's
    content.
    """
    url: str = ""
    """Relative or absolute URL of the video."""
    cover_image: Optional[str] = None
    """URL of the video thumbnail."""
    description: str = ""
    """Truncated description shown on the tile."""
    plays: str = ""
    """View count as displayed (may include abbreviations such as '1.2M')."""


class VideoDetail(BaseModel):
    """
    Full metadata scraped from a dedicated video detail page.
    """
    url: str = ""
    """Full URL of the video."""
    id: str = ""
    """Numeric or alphanumeric video identifier."""
    description: str = ""
    """Full video caption / description."""
    author_username: Optional[str] = None
    """Unique username of the uploader."""
    author_avatar: Optional[str] = None
    """URL of the uploader's avatar image."""
    plays: str = ""
    """View count."""
    likes: str = ""
    """Like count."""
    comments: str = ""
    """Comment count."""
    shares: str = ""
    """Share count."""
    saves: str = ""
    """Bookmark / save count."""
    sound: Optional[str] = None
    """Name of the background sound / music."""
    date: Optional[str] = None
    """Upload date as displayed on the page."""
    scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    """ISO-8601 timestamp of when the data was scraped."""


class Profile(BaseModel):
    """
    All publicly visible profile information available on a TikTok user page.
    """
    url: str = ""
    """Full profile URL."""
    username: str = ""
    """Unique username (e.g. '@tiktok')."""
    nickname: str = ""
    """Display name."""
    avatar: Optional[str] = None
    """URL of the profile picture."""
    bio: str = ""
    """Bio / description text."""
    follower_count: str = ""
    """Follower count as displayed."""
    following_count: str = ""
    """Following count as displayed."""
    like_count: str = ""
    """Total likes across all videos as displayed."""
    video_count: str = ""
    """Number of publicly visible videos as displayed."""
    recent_videos: List[VideoTile] = Field(default_factory=list)
    """List of video tiles scraped from the profile grid."""
    scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    """ISO-8601 timestamp of when the data was scraped."""
