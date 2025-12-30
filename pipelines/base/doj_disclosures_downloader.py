"""Download DOJ Epstein disclosure files.

Usage examples:
  # Run once with defaults.
  python pipelines/base/doj_disclosures_downloader.py

  # Dry run (no downloads), show planned actions.
  python pipelines/base/doj_disclosures_downloader.py --dry-run

  # Watch mode: recheck every 30 minutes.
  python pipelines/base/doj_disclosures_downloader.py --watch 30

  # Limit downloads to 5 files per run (useful for testing).
  python pipelines/base/doj_disclosures_downloader.py --limit 5

This script targets the DOJ Epstein disclosures page and downloads any new or
updated files from the disclosure accordion section.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.justice.gov"
TARGET_URL = "https://www.justice.gov/epstein/doj-disclosures"
OUTPUT_DIR = "outputs/doj_disclosures"
MANIFEST_NAME = "manifest.json"
LOG_NAME = "doj_disclosures_downloader.log"
USER_AGENT = "doj-disclosures-downloader/1.0 (+https://www.justice.gov/epstein/doj-disclosures)"
REQUEST_TIMEOUT = 30
RETRY_TOTAL = 3
RETRY_BACKOFF = 0.5
DOWNLOAD_DELAY_SECONDS = 0.3
DOWNLOAD_EXTENSIONS = {".zip", ".pdf", ".mp4", ".wav"}


@dataclass
class DownloadLink:
    url: str
    text: str
    heading: str


def setup_logging(output_dir: Path) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("doj_disclosures_downloader")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        output_dir / LOG_NAME,
        maxBytes=1_000_000,
        backupCount=3,
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("HEAD", "GET"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def extract_download_links(html: str, base_url: str) -> list[DownloadLink]:
    soup = BeautifulSoup(html, "html.parser")
    accordions = soup.select(".usa-accordion.usa-accordion--bordered")
    links: list[DownloadLink] = []

    for accordion in accordions:
        for button in accordion.select("button.usa-accordion__button"):
            heading_text = " ".join(button.get_text(strip=True).split())
            content = button.find_parent().find_next_sibling("div", class_="usa-accordion__content")
            if content is None:
                continue
            for anchor in content.find_all("a", href=True):
                href = anchor.get("href")
                if not href:
                    continue
                url = normalize_url(base_url, href)
                if not url:
                    continue
                text = " ".join(anchor.get_text(strip=True).split())
                links.append(DownloadLink(url=url, text=text, heading=heading_text))

    return links


def normalize_url(base_url: str, href: str) -> str | None:
    href = href.strip()
    if not href:
        return None
    return urljoin(base_url, href)


def sanitize_filename(value: str) -> str:
    decoded = unquote(value)
    decoded = decoded.replace("/", "_").replace("\\", "_")
    decoded = re.sub(r"[<>:\"|?*\x00-\x1f]", "_", decoded)
    decoded = re.sub(r"\s+", " ", decoded).strip()
    return decoded


def build_local_path(output_dir: Path, link: DownloadLink) -> Path:
    heading = sanitize_filename(link.heading) or "Other"
    dataset_folder = ""
    match = re.search(r"data\s*set\s*(\d+)", link.text, flags=re.IGNORECASE)
    if match:
        dataset_folder = f"VOL{int(match.group(1)):05d}"

    url_path = urlparse(link.url).path
    filename = sanitize_filename(Path(url_path).name)

    parts = [output_dir, heading]
    if dataset_folder:
        parts.append(sanitize_filename(dataset_folder))
    target_dir = Path(*parts)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / filename


def load_manifest(manifest_path: Path) -> dict:
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return {"entries": {}}


def save_manifest(manifest_path: Path, manifest: dict) -> None:
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)


def head_or_get_metadata(
    session: requests.Session,
    url: str,
    existing: dict | None,
) -> tuple[requests.Response | None, dict]:
    headers = {}
    if existing:
        if existing.get("etag"):
            headers["If-None-Match"] = existing["etag"]
        if existing.get("last_modified"):
            headers["If-Modified-Since"] = existing["last_modified"]

    response = session.head(url, headers=headers, allow_redirects=True, timeout=REQUEST_TIMEOUT)
    if response.status_code in {405, 403}:
        response = session.get(url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT)
    metadata = {
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "content_length": response.headers.get("Content-Length"),
        "status_code": response.status_code,
    }
    response.close()
    return response, metadata


def download_file(
    session: requests.Session,
    url: str,
    destination: Path,
    metadata: dict,
    existing: dict | None,
    dry_run: bool,
    logger: logging.Logger,
) -> tuple[bool, dict]:
    if dry_run:
        logger.info("[dry-run] Would download %s -> %s", url, destination)
        return False, {}

    headers = {}
    if existing:
        if existing.get("etag"):
            headers["If-None-Match"] = existing["etag"]
        if existing.get("last_modified"):
            headers["If-Modified-Since"] = existing["last_modified"]

    response = session.get(url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT)
    if response.status_code == 304:
        return False, {}
    response.raise_for_status()

    temp_path = destination.with_suffix(destination.suffix + ".part")
    hash_sha256 = hashlib.sha256()
    with temp_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            handle.write(chunk)
            hash_sha256.update(chunk)

    temp_path.replace(destination)

    return True, {
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "content_length": response.headers.get("Content-Length"),
        "sha256": hash_sha256.hexdigest(),
    }


def count_pdf_pages(handle) -> int:
    reader = PdfReader(handle)
    return len(reader.pages)


def get_page_count_metadata(path: Path, logger: logging.Logger) -> dict:
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            with path.open("rb") as handle:
                return {"page_count": count_pdf_pages(handle)}
        except Exception as exc:  # noqa: BLE001 - log and continue
            logger.warning("Unable to read PDF page count for %s: %s", path, exc)
            return {}

    if ext == ".zip":
        try:
            pdf_pages: dict[str, int] = {}
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if not name.lower().endswith(".pdf"):
                        continue
                    with archive.open(name) as handle:
                        pdf_pages[name] = count_pdf_pages(handle)
            if not pdf_pages:
                return {}
            return {
                "embedded_pdf_pages": {
                    "pdf_count": len(pdf_pages),
                    "total_pages": sum(pdf_pages.values()),
                    "per_pdf": pdf_pages,
                }
            }
        except Exception as exc:  # noqa: BLE001 - log and continue
            logger.warning("Unable to read PDF page counts inside %s: %s", path, exc)
            return {}

    return {}


def has_page_count_changed(existing: dict | None, current: dict) -> bool:
    if not existing or not current:
        return False
    if "page_count" in current and "page_count" in existing:
        return current["page_count"] != existing["page_count"]
    if "embedded_pdf_pages" in current and "embedded_pdf_pages" in existing:
        existing_pages = existing["embedded_pdf_pages"]
        current_pages = current["embedded_pdf_pages"]
        return current_pages.get("per_pdf") != existing_pages.get("per_pdf")
    return False


def filter_download_links(links: Iterable[DownloadLink]) -> list[DownloadLink]:
    filtered: list[DownloadLink] = []
    seen = set()
    for link in links:
        ext = Path(urlparse(link.url).path).suffix.lower()
        if ext not in DOWNLOAD_EXTENSIONS:
            continue
        if link.url in seen:
            continue
        seen.add(link.url)
        filtered.append(link)
    return filtered


def should_skip_download(metadata: dict, existing: dict | None) -> bool:
    if metadata.get("status_code") == 304:
        return True
    if not existing:
        return False
    if metadata.get("etag") and existing.get("etag") == metadata.get("etag"):
        return True
    if metadata.get("last_modified") and existing.get("last_modified") == metadata.get("last_modified"):
        return True
    if metadata.get("content_length") and existing.get("content_length") == metadata.get("content_length"):
        return True
    return False


def run_once(args: argparse.Namespace, logger: logging.Logger) -> None:
    output_dir = Path(args.output_dir)
    manifest_path = output_dir / MANIFEST_NAME

    session = build_session()
    logger.info("Fetching %s", TARGET_URL)
    html = fetch_html(session, TARGET_URL)

    raw_links = extract_download_links(html, BASE_URL)
    download_links = filter_download_links(raw_links)

    manifest = load_manifest(manifest_path)
    entries: dict = manifest.setdefault("entries", {})

    total_links = len(download_links)
    attempted = 0
    downloaded = 0
    skipped = 0
    failures = 0
    page_count_changes = 0

    for link in download_links:
        if args.limit and attempted >= args.limit:
            logger.info("Download limit reached (%s).", args.limit)
            break

        destination = build_local_path(output_dir, link)
        existing = entries.get(link.url)
        attempted += 1
        page_count_metadata: dict = {}
        page_count_changed = False

        try:
            response, metadata = head_or_get_metadata(session, link.url, existing)
            if response is not None and response.status_code == 304:
                if args.verify_page_count and destination.exists():
                    page_count_metadata = get_page_count_metadata(destination, logger)
                    page_count_changed = has_page_count_changed(existing, page_count_metadata)
                    if page_count_changed:
                        page_count_changes += 1
                        logger.warning(
                            "Page count changed for %s (local file differs from manifest).",
                            link.url,
                        )
                skipped += 1
                entries[link.url] = {
                    **(existing or {}),
                    "url": link.url,
                    "local_path": str(destination),
                    "last_seen_utc": datetime.now(timezone.utc).isoformat(),
                    **page_count_metadata,
                    "status": "page-count-changed" if page_count_changed else "skipped",
                }
                logger.info("Unchanged (304): %s", link.url)
                continue

            if should_skip_download(metadata, existing):
                if args.verify_page_count and destination.exists():
                    page_count_metadata = get_page_count_metadata(destination, logger)
                    page_count_changed = has_page_count_changed(existing, page_count_metadata)
                    if page_count_changed:
                        page_count_changes += 1
                        logger.warning(
                            "Page count changed for %s (local file differs from manifest).",
                            link.url,
                        )
                skipped += 1
                entries[link.url] = {
                    **(existing or {}),
                    "url": link.url,
                    "local_path": str(destination),
                    "last_seen_utc": datetime.now(timezone.utc).isoformat(),
                    "etag": metadata.get("etag") or existing.get("etag"),
                    "last_modified": metadata.get("last_modified") or existing.get("last_modified"),
                    "content_length": metadata.get("content_length") or existing.get("content_length"),
                    **page_count_metadata,
                    "status": "page-count-changed" if page_count_changed else "skipped",
                }
                logger.info("Unchanged: %s", link.url)
                continue

            downloaded_flag, download_metadata = download_file(
                session=session,
                url=link.url,
                destination=destination,
                metadata=metadata,
                existing=existing,
                dry_run=args.dry_run,
                logger=logger,
            )

            if downloaded_flag:
                downloaded += 1
                status = "downloaded"
                logger.info("Downloaded %s -> %s", link.url, destination)
                page_count_metadata = get_page_count_metadata(destination, logger)
                time.sleep(DOWNLOAD_DELAY_SECONDS)
            else:
                if args.dry_run:
                    status = "dry-run"
                else:
                    status = "skipped"
                    skipped += 1

            safe_download_metadata = download_metadata or {}
            safe_existing = existing or {}
            entries[link.url] = {
                **safe_existing,
                "url": link.url,
                "local_path": str(destination),
                "last_seen_utc": datetime.now(timezone.utc).isoformat(),
                "etag": safe_download_metadata.get("etag") or metadata.get("etag"),
                "last_modified": safe_download_metadata.get("last_modified") or metadata.get("last_modified"),
                "content_length": safe_download_metadata.get("content_length") or metadata.get("content_length"),
                "sha256": safe_download_metadata.get("sha256") or safe_existing.get("sha256"),
                **page_count_metadata,
                "status": status,
            }
        except Exception as exc:  # noqa: BLE001 - capture for logging
            failures += 1
            logger.exception("Failed to process %s: %s", link.url, exc)
            entries[link.url] = {
                **(existing or {}),
                "url": link.url,
                "local_path": str(destination),
                "last_seen_utc": datetime.now(timezone.utc).isoformat(),
                "status": "failed",
            }

    save_manifest(manifest_path, manifest)

    summary = (
        "Run summary:\n"
        f"  Total links found: {total_links}\n"
        f"  Downloads attempted: {attempted}\n"
        f"  Files downloaded: {downloaded}\n"
        f"  Skipped (unchanged): {skipped}\n"
        f"  Page count changes detected: {page_count_changes}\n"
        f"  Failures: {failures}"
    )
    logger.info(summary)
    print(summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download DOJ Epstein disclosure files.")
    parser.add_argument(
        "--output-dir",
        default=OUTPUT_DIR,
        help="Folder for downloads, manifest, and logs (default: outputs/doj_disclosures).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List downloads without saving files.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check (default).",
    )
    parser.add_argument(
        "--watch",
        type=float,
        help="Repeat every N minutes until interrupted.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of downloads to attempt per run.",
    )
    parser.add_argument(
        "--verify-page-count",
        action="store_true",
        help=(
            "Verify PDF page counts for existing downloads (including PDFs inside ZIPs) "
            "and flag entries when counts differ from the manifest."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    logger = setup_logging(output_dir)

    if args.watch:
        logger.info("Starting watch mode: every %s minutes", args.watch)
        while True:
            run_once(args, logger)
            logger.info("Sleeping for %s minutes", args.watch)
            time.sleep(args.watch * 60)
    else:
        run_once(args, logger)


if __name__ == "__main__":
    main()
