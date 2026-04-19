#!/usr/bin/env python3
"""
Crawler aktów prawnych z API ELI Sejmu (ISAP).
Dokumentacja interfejsu: https://api.sejm.gov.pl/eli/openapi/ui/
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

BASE_URL = "https://api.sejm.gov.pl/eli"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_json(session: requests.Session, url: str) -> dict[str, Any]:
    r = session.get(url, headers={"accept": "application/json"}, timeout=120)
    r.raise_for_status()
    return r.json()


def fetch_html(session: requests.Session, url: str) -> str:
    r = session.get(url, headers={"accept": "text/html"}, timeout=120)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def fetch_bytes(session: requests.Session, url: str, accept: str) -> bytes:
    r = session.get(url, headers={"accept": accept}, timeout=180)
    r.raise_for_status()
    return r.content


def eli_to_acts_path(eli: str) -> str | None:
    """ELI np. DU/2017/2 -> prefiks ścieżki w API: DU/2017/2 (doklejamy /text.html lub /text.pdf)."""
    parts = eli.strip("/").split("/")
    if len(parts) != 3:
        return None
    return f"{parts[0]}/{parts[1]}/{parts[2]}"


def crawl_year(
    year: int,
    publisher: str,
    mongo_uri: str,
    db_name: str,
    coll_name: str,
    assets_root: Path,
    sleep_s: float,
    skip_html: bool,
    skip_pdf: bool,
) -> None:
    session = requests.Session()
    session.headers.setdefault("User-Agent", "isap-crawler/1.0 (+local research)")

    list_url = f"{BASE_URL}/acts/{publisher}/{year}?sortBy=change&sortDir=desc"
    logging.info("Pobieranie listy: %s", list_url)
    listing = fetch_json(session, list_url)
    items: list[dict[str, Any]] = listing.get("items") or []
    total = listing.get("count", len(items))
    logging.info("Liczba aktów (count=%s), pozycji w odpowiedzi: %s", total, len(items))

    client = MongoClient(mongo_uri)
    coll: Collection = client[db_name][coll_name]
    coll.create_index("address", unique=True)

    year_dir = assets_root / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)

    for idx, summary in enumerate(items, start=1):
        address = summary.get("address")
        if not address:
            logging.warning("Pominięto wpis bez address: %s", summary)
            continue

        detail_url = f"{BASE_URL}/acts/{address}"
        logging.info("[%s/%s] Detale: %s", idx, len(items), detail_url)
        try:
            detail = fetch_json(session, detail_url)
        except requests.RequestException as e:
            logging.error("Błąd pobierania detali %s: %s", address, e)
            continue

        refs = detail.get("references") or {}
        akty_zmienione = refs.get("Akty zmienione")

        doc: dict[str, Any] = dict(detail)
        doc["Akty zmienione"] = akty_zmienione
        doc["crawledAt"] = utc_now()
        doc["sourceYear"] = year
        doc["sourcePublisher"] = publisher

        safe_name = "".join(c if c.isalnum() or c in "-._" else "_" for c in address)
        eli_base = eli_to_acts_path(str(detail["ELI"])) if detail.get("ELI") else None

        if not skip_html and detail.get("textHTML") and eli_base:
            html_url = f"{BASE_URL}/acts/{eli_base}/text.html"
            try:
                html = fetch_html(session, html_url)
                out_path = year_dir / f"{safe_name}.html"
                out_path.write_text(html, encoding="utf-8")
                doc["htmlLocalPath"] = f"{year}/{safe_name}.html"
                doc.pop("htmlError", None)
                logging.info("Zapisano HTML: %s", out_path)
            except requests.RequestException as e:
                logging.warning("Brak HTML dla %s (%s): %s", address, html_url, e)
                doc["htmlLocalPath"] = None
                doc["htmlError"] = str(e)
        elif not skip_html:
            doc["htmlLocalPath"] = None

        if not skip_pdf and detail.get("textPDF") and eli_base:
            pdf_url = f"{BASE_URL}/acts/{eli_base}/text.pdf"
            try:
                data = fetch_bytes(session, pdf_url, "application/pdf")
                if not data.startswith(b"%PDF"):
                    raise ValueError(f"oczekiwano PDF, otrzymano {len(data)} B")
                out_pdf = year_dir / f"{safe_name}.pdf"
                out_pdf.write_bytes(data)
                doc["pdfLocalPath"] = f"{year}/{safe_name}.pdf"
                doc.pop("pdfError", None)
                logging.info("Zapisano PDF: %s (%s B)", out_pdf, len(data))
            except (requests.RequestException, OSError, ValueError) as e:
                logging.warning("Brak PDF dla %s (%s): %s", address, pdf_url, e)
                doc["pdfLocalPath"] = None
                doc["pdfError"] = str(e)
        elif not skip_pdf:
            doc["pdfLocalPath"] = None

        try:
            coll.update_one({"address": address}, {"$set": doc}, upsert=True)
        except PyMongoError as e:
            logging.error("MongoDB zapis %s: %s", address, e)

        if sleep_s > 0:
            time.sleep(sleep_s)

    client.close()
    logging.info("Zakończono rok %s", year)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Crawler ISAP / ELI -> MongoDB + pliki HTML i PDF lokalnie"
    )
    p.add_argument("--year", type=int, required=True, help="Rok obowiązywania wykazu (np. 1990)")
    p.add_argument(
        "--publisher",
        default=os.environ.get("ISAP_PUBLISHER", "DU"),
        help="Wydawca w ścieżce listy (domyślnie DU = Dziennik Ustaw)",
    )
    p.add_argument(
        "--mongodb-uri",
        default=os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017/"),
        help="URI MongoDB",
    )
    p.add_argument(
        "--db",
        default=os.environ.get("ISAP_MONGO_DB", "legal_acts"),
        help="Nazwa bazy danych",
    )
    p.add_argument(
        "--collection",
        default=os.environ.get("ISAP_MONGO_COLLECTION", "isap"),
        help="Nazwa kolekcji",
    )
    p.add_argument(
        "--html-dir",
        type=Path,
        default=Path(os.environ.get("ISAP_HTML_DIR", "isap")),
        help="Katalog bazowy dla HTML i PDF (pliki w podkatalogu {rok}/)",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=float(os.environ.get("ISAP_SLEEP", "0.15")),
        help="Pauza między aktami (sekundy), żeby nie obciążać API",
    )
    p.add_argument("--skip-html", action="store_true", help="Nie pobieraj plików HTML")
    p.add_argument("--skip-pdf", action="store_true", help="Nie pobieraj plików PDF")
    p.add_argument("-v", "--verbose", action="store_true", help="Log DEBUG")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.DEBUG if args.verbose else logging.WARNING)

    assets_root = args.html_dir.resolve()
    try:
        crawl_year(
            year=args.year,
            publisher=args.publisher,
            mongo_uri=args.mongodb_uri,
            db_name=args.db,
            coll_name=args.collection,
            assets_root=assets_root,
            sleep_s=args.sleep,
            skip_html=args.skip_html,
            skip_pdf=args.skip_pdf,
        )
    except KeyboardInterrupt:
        logging.error("Przerwano przez użytkownika")
        return 130
    except (requests.RequestException, PyMongoError) as e:
        logging.error("%s: %s", type(e).__name__, e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
