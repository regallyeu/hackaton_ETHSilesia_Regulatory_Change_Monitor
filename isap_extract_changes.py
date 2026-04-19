#!/usr/bin/env python3
"""
Odczytuje akty z Mongo (kolekcja isap), ekstrahuje tekst z PDF i heurystycznie
wykrywa zmiany wprowadzane przez akt zmieniający (np. rozporządzenie zmieniające).

Wynik zapisuje do kolekcji ``changes`` w tej samej bazie (domyślnie legal_acts).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

# --- tekst PDF ---


def pdf_to_text(path: Path) -> str:
    doc = fitz.open(path)
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "\n".join(parts)


# --- wykrywanie aktu zmienianego ---

# Ustawa zmieniająca: Art. 1. W ustawie … (Dz. U. …) w art. N:
# „poz. 439 i 1792)” — po „poz.” bywa kilka numerów przed „)”
ART1_USTAWA = re.compile(
    r"Art\.\s*1\.\s*W\s+ustawie\s+"
    r"[\s\S]{0,20000}?"
    r"\(\s*Dz\.\s*U\.\s*z\s*(\d{4})\s*r\.\s*poz\.\s*([^)]+)\)",
    re.IGNORECASE | re.UNICODE,
)


def _first_integer(s: str) -> int | None:
    m = re.search(r"\d+", s)
    return int(m.group(0)) if m else None

# Rozporządzenie / inne: § 1. … wprowadza się
SECTION1_AMENDED = re.compile(
    r"§\s*1\.\s*"
    r"W\s+(?:ustawie|rozporządzeniu|obwieszczeniu)\s+"
    r"[\s\S]{0,8000}?"
    r"\(\s*Dz\.\s*U\.\s*z\s*(\d{4})\s*r\.\s*poz\.\s*(\d+)\s*\)\s*"
    r"wprowadza\s+się",
    re.IGNORECASE | re.UNICODE,
)

# Ten sam rok co akt zmieniający: „(Dz. U. poz. 834)”
SECTION1_AMENDED_NOYEAR = re.compile(
    r"§\s*1\.\s*"
    r"W\s+(?:ustawie|rozporządzeniu|obwieszczeniu)\s+"
    r"[\s\S]{0,8000}?"
    r"\(\s*Dz\.\s*U\.\s*poz\.\s*(\d+)\s*\)\s*"
    r"wprowadza\s+się",
    re.IGNORECASE | re.UNICODE,
)


def find_amended_dzu(text: str, amending_year: int | None) -> tuple[int, int] | None:
    head = text[:30000]
    m = ART1_USTAWA.search(head)
    if m:
        y = int(m.group(1))
        p0 = _first_integer(m.group(2))
        if p0 is not None:
            return y, p0
    m = SECTION1_AMENDED.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = SECTION1_AMENDED_NOYEAR.search(text)
    if m and amending_year is not None:
        return amending_year, int(m.group(1))
    return None


# --- ciało zmian: „wprowadza się…” albo „w art. N:” (ustawy) do § 2 / Art. 2 ---


def extract_changes_body(text: str) -> tuple[str | None, str | None]:
    """
    Zwraca (treść_bloku_zmian, numer_artykułu_z_nagłówka).
    Dla aktów w stylu rozporządzenia drugi element to None.
    """
    m = re.search(
        r"wprowadza\s+się\s+następujące\s+zmiany\s*:\s*",
        text,
        flags=re.IGNORECASE | re.UNICODE | re.DOTALL,
    )
    if m:
        body = text[m.end() :]
        cut = re.search(r"(?m)^\s*§\s*2\.\s", body)
        if cut:
            body = body[: cut.start()]
        cut_art = re.search(r"(?m)^\s*Art\.\s*(\d+)\.\s+W\s+ustawie", body)
        if cut_art and int(cut_art.group(1)) >= 2:
            body = body[: cut_art.start()]
        return body.strip(), None

    m = re.search(
        r"(?ms)Art\.\s*1\.[\s\S]{0,25000}?"
        r"\(\s*Dz\.\s*U\.\s*z\s*\d{4}\s*r\.\s*poz\.\s*\d+\s*\)\s*"
        r"w\s+art\.\s*(\d+[a-z]?)\s*:\s*",
        text,
        re.IGNORECASE | re.UNICODE,
    )
    if m:
        art = m.group(1)
        body = text[m.end() :]
        cut = re.search(r"(?m)^\s*Art\.\s*2\.\s", body)
        if cut:
            body = body[: cut.start()]
        return body.strip(), art

    return None, None



# Wzorce na początku fragmentu (pierwsze ~1200 znaków, jedna linia logicznie)
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "dodanie_zakresu_artykulow_po_artykule",
        re.compile(
            r"po\s+art\.\s*(\d+[a-z]?)\s+dodaje\s+się\s+art\.\s*"
            r"(\d+[a-z]?[–\u2013\-]\d+[a-z]?)\s+w\s+brzmieniu",
            re.I | re.UNICODE,
        ),
    ),
    (
        "dodanie_dwoch_artykulow_po_artykule",
        re.compile(
            r"po\s+art\.\s*(\d+[a-z]?)\s+dodaje\s+się\s+art\.\s*(\d+[a-z]?)\s+i\s+art\.\s*(\d+[a-z]?)\s+w\s+brzmieniu",
            re.I | re.UNICODE,
        ),
    ),
    (
        "dodanie_artykulu_po_artykule",
        re.compile(
            r"po\s+art\.\s*(\d+[a-z]?)\s+dodaje\s+się\s+art\.\s*(\d+[a-z]?)\s+w\s+brzmieniu",
            re.I | re.UNICODE,
        ),
    ),
    (
        "zastapienie_wyrazow_w_ust_i_pkt",
        re.compile(
            r"w\s+ust\.\s*(\d+[a-z]?)\s+w\s+pkt\s*(\d+)\s+i\s+w\s+ust\.\s*(\d+[a-z]?)\s+wyrazy?",
            re.I | re.UNICODE,
        ),
    ),
    (
        "zastapienie_wyrazow_w_ustepie",
        re.compile(
            r"w\s+art\.\s*(\d+[a-z]?)\s+w\s+ust\.\s*(\d+[a-z]?)\s+wyrazy?\s+",
            re.I | re.UNICODE,
        ),
    ),
    (
        "wprowadzenie_do_wyliczenia_w_artykule",
        re.compile(
            r"w\s+art\.\s*(\d+[a-z]?)\s+w\s+ust\.\s*(\d+[a-z]?)\s+wprowadzenie\s+do\s+wyliczenia\s+otrzymuje\s+brzmienie",
            re.I | re.UNICODE,
        ),
    ),
    (
        "nowe_brzmienie_ustępu_w_artykule",
        re.compile(
            r"w\s+art\.\s*(\d+[a-z]?)\s+ust\.\s*(\d+[a-z]?)\s+otrzymuje\s+brzmienie",
            re.I | re.UNICODE,
        ),
    ),
    (
        "po_ustępie_dodanie_wielu_ustępów",
        re.compile(
            r"po\s+ust\.\s*(\d+[a-z]?)\s+dodaje\s+się\s+ust\.\s*"
            r"(\d+[a-z]?(?:\s+i\s+\d+[a-z]?)+)\s+w\s+brzmieniu",
            re.I | re.UNICODE,
        ),
    ),
    (
        "po_ustępie_dodanie_ustępu",
        re.compile(
            r"po\s+ust\.\s*(\d+[a-z]?)\s+dodaje\s+się\s+ust\.\s*(\d+[a-z]?)\s+w\s+brzmieniu",
            re.I | re.UNICODE,
        ),
    ),
    (
        "dodanie_ustępu_skrót",
        re.compile(
            r"^\s*dodaje\s+się\s+ust\.\s*(\d+[a-z]?)\s+w\s+brzmieniu",
            re.I | re.UNICODE,
        ),
    ),
    (
        "dodanie_ustępu",
        re.compile(
            r"w\s+§\s*(\d+[a-z]?)\s+dodaje\s+się\s+ust\.\s*(\d+[a-z]?)",
            re.I | re.UNICODE,
        ),
    ),
    (
        "nowe_brzmienie_ustępu",
        re.compile(
            r"w\s+§\s*(\d+[a-z]?)\s+ust\.\s*(\d+[a-z]?)\s+otrzymuje\s+brzmienie",
            re.I | re.UNICODE,
        ),
    ),
    (
        "oznaczenie_treści_i_dodanie_ustępu",
        re.compile(
            r"w\s+§\s*(\d+[a-z]?)\s+dotychczasową\s+treść\s+oznacza\s+się\s+jako\s+ust\.\s*\d+\s+i\s+dodaje\s+się\s+ust\.\s*(\d+[a-z]?)",
            re.I | re.UNICODE,
        ),
    ),
    (
        "edycja_paragrafu",
        re.compile(r"w\s+§\s*(\d+[a-z]?)\s*:", re.I | re.UNICODE),
    ),
    (
        "uchylenie",
        re.compile(r"uchyla\s+się", re.I | re.UNICODE),
    ),
    (
        "dodanie_po_punkcie",
        re.compile(
            r"po\s+pkt\s+(\d+[a-z]?)\s+dodaje\s+się\s+pkt",
            re.I | re.UNICODE,
        ),
    ),
    (
        "nowe_brzmienie_punktu_w_paragrafie",
        re.compile(
            r"w\s+§\s*(\d+[a-z]?)\s+pkt\s+(\d+[a-z]?)\s+otrzymuje\s+brzmienie",
            re.I | re.UNICODE,
        ),
    ),
    (
        "nowe_brzmienie_punktu",
        re.compile(r"pkt\s+(\d+[a-z]?)\s+otrzymuje\s+brzmienie", re.I | re.UNICODE),
    ),
    (
        "wprowadzenie_wyliczenia_brzmienie",
        re.compile(
            r"wprowadzenie\s+do\s+wyliczenia\s+otrzymuje\s+brzmienie",
            re.I | re.UNICODE,
        ),
    ),
]


def classify_fragment(fragment: str) -> dict[str, Any]:
    frag = fragment.strip()
    head = " ".join(frag[:1200].split())
    paragraf = ""
    ustęp = ""
    punkt = ""
    kotwica_ustępu = ""
    artykul_val = ""
    ustęp_dodatkowy = ""
    rodzaj = "nieokreślone"

    for label, pat in PATTERNS:
        if label == "dodanie_ustępu_skrót":
            m = pat.match(frag[:400])
        else:
            m = pat.search(head)
        if not m:
            continue
        rodzaj = label
        if label == "uchylenie":
            break
        if label == "wprowadzenie_wyliczenia_brzmienie":
            break
        if label == "dodanie_zakresu_artykulow_po_artykule":
            paragraf = m.group(1)
            ustęp = m.group(2)
            break
        if label == "dodanie_dwoch_artykulow_po_artykule":
            paragraf = m.group(1)
            ustęp = m.group(2)
            punkt = m.group(3)
            break
        if label == "dodanie_artykulu_po_artykule":
            paragraf = m.group(1)
            ustęp = m.group(2)
            break
        if label == "zastapienie_wyrazow_w_ust_i_pkt":
            ustęp = m.group(1)
            punkt = m.group(2)
            ustęp_dodatkowy = m.group(3)
            break
        if label == "zastapienie_wyrazow_w_ustepie":
            artykul_val = m.group(1)
            ustęp = m.group(2)
            paragraf = ""
            break
        if label == "wprowadzenie_do_wyliczenia_w_artykule":
            artykul_val = m.group(1)
            ustęp = m.group(2)
            paragraf = ""
            break
        if label == "nowe_brzmienie_ustępu_w_artykule":
            artykul_val = m.group(1)
            ustęp = m.group(2)
            paragraf = ""
            break
        if label == "po_ustępie_dodanie_wielu_ustępów":
            kotwica_ustępu = m.group(1)
            ustęp = m.group(2)
            break
        if label == "po_ustępie_dodanie_ustępu":
            kotwica_ustępu = m.group(1)
            ustęp = m.group(2)
            break
        if label == "dodanie_ustępu_skrót":
            ustęp = m.group(1)
            break
        if label == "edycja_paragrafu":
            paragraf = m.group(1)
            break
        if label == "nowe_brzmienie_punktu_w_paragrafie":
            paragraf = m.group(1)
            punkt = m.group(2)
            break
        if label == "dodanie_po_punkcie" or label == "nowe_brzmienie_punktu":
            paragraf = ""
            punkt = m.group(1)
            break
        paragraf = m.group(1)
        if len(m.groups()) >= 2:
            ustęp = m.group(2)
        break

    out: dict[str, Any] = {
        "paragraf": paragraf,
        "ustęp": ustęp,
        "punkt": punkt,
        "kotwica_ustępu": kotwica_ustępu,
        "rodzaj": rodzaj,
        "tekst": fragment.strip()[:50000],
    }
    if artykul_val:
        out["artykuł"] = artykul_val
    if ustęp_dodatkowy:
        out["ustęp_dodatkowy"] = ustęp_dodatkowy
    return out


ANY_NUMBERED = re.compile(r"(?m)^\s*(\d+)\)\s*")


def _is_outer_list_item(body: str, idx_after_paren: int) -> bool:
    """Pomija „1) pkt …” wewnątrz cytatów — zostawia listę zmian na poziomie głównym."""
    tail = body[idx_after_paren : idx_after_paren + 800]
    return bool(
        re.match(
            r"\s*(?:w\s+§|w\s+art\.|w\s+ust\.|uchyla\s+się|po\s+pkt|po\s+ust\.|po\s+art\.|dodaje\s+się\s+ust\.)",
            tail,
            re.IGNORECASE | re.UNICODE,
        )
    )


def split_art_style_operations(body: str) -> list[str]:
    """
    Lista zmian w obrębie jednego artykułu (np. „w art. 24:”): kolejne
    „po ust. … dodaje się ust. … w brzmieniu:” (także „ust. 2a i 2b”) oraz „dodaje się ust. … w brzmieniu:”.
    """
    pat = re.compile(
        r"(?mi)^\s*(?:po\s+ust\.\s*\d+[a-z]?\s+dodaje\s+się\s+ust\.[^\n]+?\s+w\s+brzmieniu|"
        r"dodaje\s+się\s+ust\.\s*\d+[a-z]?)\s*:",
    )
    matches = list(pat.finditer(body))
    if not matches:
        return split_numbered_items(body)
    chunks: list[str] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunks.append(body[m.start() : end].strip())
    return chunks


ART_W_USTAWIE_W_ART = re.compile(
    r"(?ms)^\s*Art\.\s*(\d+)\.\s+W\s+ustawie\s+"
    r"((?:(?!^\s*Art\.\s*\d+\.)[\s\S])*?)"
    r"\)\s*w\s+art\.\s*(\d+[a-z]?)\s*:\s*",
    re.IGNORECASE | re.UNICODE,
)


def _build_w_art_colon_sections(text: str) -> list[dict[str, Any]]:
    """Art. N. W ustawie … (Dz.U. …) w art. X: — osobna składnia od „wprowadza się…”."""
    out: list[dict[str, Any]] = []
    for m in ART_W_USTAWIE_W_ART.finditer(text):
        k = int(m.group(1))
        if k == 1:
            continue
        art_scope = m.group(3)
        start = m.end()
        rest = text[start:]
        end_m = re.search(r"(?m)^\s*Art\.\s*\d+\.\s", rest)
        body = rest[: end_m.start()].strip() if end_m else rest.strip()
        chunks = split_numbered_items(body)
        if not chunks:
            chunks = split_art_style_operations(body)
        else:
            flat: list[str] = []
            for c in chunks:
                flat.extend(split_po_art_blocks(c))
            chunks = flat
        for c in chunks:
            if not c.strip():
                continue
            rec = classify_fragment(c)
            rec["artykuł"] = art_scope
            rec["sekcja"] = f"Art. {k}"
            out.append(rec)
    return out


def split_po_art_blocks(chunk: str) -> list[str]:
    """W obrębie jednego „1)” bywa „po art. …” po wcześniejszej zmianie — rozdzielamy."""
    chunk = chunk.strip()
    if not chunk:
        return []
    parts = re.split(r"(?mi)(?=^\s*po\s+art\.\s*\d)", chunk)
    parts = [p.strip() for p in parts if p.strip()]
    return parts if len(parts) > 1 else [chunk]


def _build_change_records_art2_po_art(text: str) -> list[dict[str, Any]]:
    """Art. 2. W ustawie … ) po art. … — inna składnia niż „wprowadza się następujące zmiany”."""
    m0 = re.search(r"(?m)^\s*Art\.\s*2\.\s+W\s+ustawie", text)
    if not m0:
        return []
    rest = text[m0.end() :]
    m_po = re.search(r"\)\s*(po\s+art\.\s*[\s\S]+)", rest, re.IGNORECASE | re.UNICODE)
    if not m_po:
        return []
    body = m_po.group(1).strip()
    cut = re.search(r"(?m)^\s*Art\.\s*3\.\s", body)
    if cut:
        body = body[: cut.start()].strip()
    rec = classify_fragment(body)
    rec["sekcja"] = "Art. 2"
    return [rec]


def split_numbered_items(body: str) -> list[str]:
    """Dzieli treść na fragmenty „1) …”, „2) …” poziomu głównego (po wprowadza się…)."""
    matches = [m for m in ANY_NUMBERED.finditer(body) if _is_outer_list_item(body, m.end())]
    if not matches:
        return [body] if body.strip() else []
    out: list[str] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[start:end].strip()
        if chunk:
            out.append(chunk)
    return out


def build_change_records(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ustawa_art1 = bool(ART1_USTAWA.search(text[:30000]))
    body, artykuł = extract_changes_body(text)
    if body:
        if artykuł:
            chunks = split_art_style_operations(body)
        else:
            raw = split_numbered_items(body)
            chunks = []
            for c in raw:
                chunks.extend(split_po_art_blocks(c))
        if not chunks:
            chunks = [body]
        for c in chunks:
            rec = classify_fragment(c)
            if artykuł:
                rec["artykuł"] = artykuł
            if ustawa_art1:
                rec["sekcja"] = "Art. 1"
            out.append(rec)
    out.extend(_build_change_records_art2_po_art(text))
    out.extend(_build_w_art_colon_sections(text))
    return out


def year_from_act(doc: dict[str, Any]) -> int | None:
    y = doc.get("year")
    if isinstance(y, int):
        return y
    if isinstance(y, str) and y.isdigit():
        return int(y)
    return None


def resolve_isap_by_dzu(isap: Collection, year: int, pos: int) -> dict[str, Any] | None:
    return isap.find_one({"publisher": "DU", "year": year, "pos": pos})


def run(
    mongo_uri: str,
    db_name: str,
    isap_coll: str,
    changes_coll: str,
    assets_dir: Path,
    year_filter: int | None,
    limit: int | None,
) -> int:
    client = MongoClient(mongo_uri)
    isap: Collection = client[db_name][isap_coll]
    changes: Collection = client[db_name][changes_coll]
    changes.create_index("akt_zmieniający.address", unique=True)

    query: dict[str, Any] = {"pdfLocalPath": {"$type": "string", "$ne": ""}}
    if year_filter is not None:
        query["year"] = year_filter

    cursor = isap.find(query).sort("address", 1)
    if limit:
        cursor = cursor.limit(limit)

    processed = 0
    for doc in cursor:
        pdf_rel = doc.get("pdfLocalPath")
        if not pdf_rel or not isinstance(pdf_rel, str):
            continue
        pdf_path = assets_dir / pdf_rel
        if not pdf_path.is_file():
            logging.warning("Brak pliku PDF: %s (address=%s)", pdf_path, doc.get("address"))
            continue

        try:
            text = pdf_to_text(pdf_path)
        except (RuntimeError, OSError, ValueError) as e:
            logging.error("PDF %s: %s", pdf_path, e)
            continue

        amending_year = year_from_act(doc)
        amended = find_amended_dzu(text, amending_year)
        amended_doc = None
        amended_payload: dict[str, Any]
        if amended:
            y, p = amended
            amended_doc = resolve_isap_by_dzu(isap, y, p)
            amended_payload = {
                "rok": y,
                "poz": p,
                "ELI": amended_doc.get("ELI") if amended_doc else f"DU/{y}/{p}",
                "address": amended_doc.get("address") if amended_doc else None,
                "tytuł": amended_doc.get("title") if amended_doc else None,
            }
        else:
            amended_payload = {
                "rok": None,
                "poz": None,
                "ELI": None,
                "address": None,
                "tytuł": None,
            }

        zmiany = build_change_records(text)

        if not zmiany:
            logging.info("Brak wykrytych zmian — pominięto zapis do changes: %s", doc.get("address"))
            continue

        out_doc = {
            "akt_zmieniający": {
                "address": doc.get("address"),
                "ELI": doc.get("ELI"),
                "tytuł": doc.get("title"),
                "rok": doc.get("year"),
                "poz": doc.get("pos"),
            },
            "akt_zmieniany": amended_payload,
            "zmiany": zmiany,
            "pdfLocalPath": pdf_rel,
            "analyzedAt": datetime.now(timezone.utc),
            "wykryto_blok_zmian": True,
        }

        try:
            changes.update_one(
                {"akt_zmieniający.address": doc.get("address")},
                {"$set": out_doc},
                upsert=True,
            )
        except PyMongoError as e:
            logging.error("Mongo zapis %s: %s", doc.get("address"), e)
            continue

        processed += 1
        logging.info(
            "Zapisano: %s -> zmieniany %s, fragmentów zmian: %s",
            doc.get("address"),
            amended_payload.get("ELI") or "nie rozpoznano",
            len(zmiany),
        )

    client.close()
    logging.info("Przetworzono dokumentów: %s", processed)
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="PDF z isap -> wykrycie aktu zmienianego i listy zmian -> MongoDB.changes"
    )
    p.add_argument(
        "--mongodb-uri",
        default=os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017/"),
    )
    p.add_argument("--db", default=os.environ.get("ISAP_MONGO_DB", "legal_acts"))
    p.add_argument("--isap-collection", default=os.environ.get("ISAP_MONGO_COLLECTION", "isap"))
    p.add_argument(
        "--changes-collection",
        default=os.environ.get("ISAP_CHANGES_COLLECTION", "changes"),
    )
    p.add_argument(
        "--assets-dir",
        type=Path,
        default=Path(os.environ.get("ISAP_HTML_DIR", "isap")),
        help="Katalog z PDF (jak pdfLocalPath względem tego katalogu)",
    )
    p.add_argument("--year", type=int, default=None, help="Tylko akty z danego roku (pole year)")
    p.add_argument("--limit", type=int, default=None, help="Maks. liczba aktów do analizy")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    logging.getLogger("pymongo").setLevel(logging.WARNING)

    try:
        return run(
            mongo_uri=args.mongodb_uri,
            db_name=args.db,
            isap_coll=args.isap_collection,
            changes_coll=args.changes_collection,
            assets_dir=args.assets_dir.resolve(),
            year_filter=args.year,
            limit=args.limit,
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
