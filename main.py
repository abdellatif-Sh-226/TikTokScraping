"""
Command-line entry point for the TikTok scraper.

Usage
-----
    python main.py profile https://www.tiktok.com/@username
    python main.py video   https://www.tiktok.com/@username/video/1234567890

Optional flags
--------------
    --no-save          Print data to stdout without writing JSON files.
    --headless         Run in headless mode (default: True).
    --visible          Run with visible browser (overrides headless).
    --captcha-wait N   Wait N seconds after page load for manual CAPTCHA solve.
"""

import argparse
import asyncio
import sys

from scraper import TikTokScraper
from utils import get_logger

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape publicly available TikTok profile and video data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "type",
        choices=["profile", "video"],
        help="Type of page to scrape.",
    )
    parser.add_argument(
        "url",
        help="Full TikTok URL (profile or video).",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print result to stdout instead of writing a JSON file.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run browser in headless mode (invisible).",
    )
    parser.add_argument(
        "--captcha-wait",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait N seconds after page load for manual CAPTCHA solving.",
    )
    return parser


async def _amain() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    scraper = TikTokScraper(captcha_wait=args.captcha_wait)
    scraper._config.browser_headless = args.headless

    try:
        await scraper.start()

        if args.type == "profile":
            result = await scraper.scrape_profile(args.url, save=not args.no_save)
        else:
            result = await scraper.scrape_video(args.url, save=not args.no_save)

        # If --no-save, print JSON to stdout
        if args.no_save:
            print(result.model_dump_json(indent=2))

    except Exception:
        logger.exception("Fatal error during scraping.")
        sys.exit(1)
    finally:
        await scraper.stop()


def main() -> None:
    """Synchronous entry point required by setuptools / console_scripts."""
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
