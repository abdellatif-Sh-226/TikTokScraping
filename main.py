"""
Command-line entry point for the TikTok scraper.

Usage
-----
    python main.py profile https://www.tiktok.com/@username
    python main.py video   https://www.tiktok.com/@username/video/1234567890

Optional flags
--------------
    --no-save          Print data to stdout without writing JSON files.
    --headless         Run in headless mode (invisible).
    --captcha-wait N   Wait N seconds after page load for manual CAPTCHA solve.
    --login-wait N     Wait N seconds on TikTok.com for manual login.
    --like             Like the video after loading.
    --comment TEXT     Post a comment on the video.
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
    parser.add_argument(
        "--login-wait",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait N seconds before scraping so you can log in manually.",
    )
    parser.add_argument(
        "--like",
        action="store_true",
        help="Like the video after loading the page.",
    )
    parser.add_argument(
        "--comment",
        type=str,
        default="",
        metavar="TEXT",
        help="Post a comment on the video.",
    )
    return parser


async def _amain() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    scraper = TikTokScraper(captcha_wait=args.captcha_wait)
    scraper._config.browser_headless = args.headless

    try:
        await scraper.start()

        # If --login-wait, go to TikTok.com first and wait for manual login
        if args.login_wait:
            logger.info("Waiting %d s for manual login …", args.login_wait)
            page = await scraper._context.new_page()
            await page.goto("https://www.tiktok.com", wait_until="domcontentloaded")
            await page.wait_for_timeout(args.login_wait * 1000)
            await page.close()

        if args.type == "profile":
            result = await scraper.scrape_profile(args.url, save=not args.no_save)
        else:
            result = await scraper.scrape_video(
                args.url,
                save=not args.no_save,
                like=args.like,
                comment=args.comment,
            )

        # If --no-save, print JSON to stdout
        if args.no_save:
            try:
                print(result.model_dump_json(indent=2))
            except UnicodeEncodeError:
                sys.stdout.reconfigure(encoding="utf-8")
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
