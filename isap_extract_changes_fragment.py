#!/usr/bin/env python3
"""
Wykrywa i wycina z tekstu aktu zmieniającego „fragmenty zmian” w stylu:

  po art. 9a dodaje się art. 9aa w brzmieniu:
  „…cytat…”;

  N) w art. 4j po ust. 3a dodaje się ust. 3b w brzmieniu:
  „…cytat…”;

Wewnątrz cytatu mogą występować listy „1)”, „2)” itd. — nie są traktowane
jako koniec fragmentu (koniec to domykające „…” przed „;” lub przed kolejnym
punktem numerowanym na poziomie głównym).

Zapis do MongoDB (kolekcja ``changes``): ten sam dokument i ``update_one`` co
w ``isap_extract_changes.py`` — pole ``zmiany`` budowane z wykrytych fragmentów
(zgodne klucze ``paragraf`` / ``ustęp`` / ``kotwica_ustępu`` / ``artykuł`` /
``rodzaj`` / ``tekst`` jak w rekordach z ``classify_fragment``).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from isap_extract_changes import (
    find_amended_dzu,
    pdf_to_text,
    resolve_isap_by_dzu,
    year_from_act,
)


# Otwierający / zamykający polski cytat w aktach
_OPEN_QUOTE = "\u201e"  # „
_CLOSE_QUOTE = "\u201d"  # ”


@dataclass
class ChangeFragment:
    rodzaj: str
    """po_art_dodaje_art | numerowany_w_art_po_ust_dodaje_ust"""
    surowy_nagłówek: str
    cytat: str
    """Treść wewnątrz „…”, bez zewnętrznych cudzysłowów."""
    pełny_tekst: str
    pola: dict[str, Any]


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n\f\v":
        i += 1
    return i


def _extract_quote_after_brzmieniu(s: str, start: int) -> tuple[str, int] | None:
    """
    Po fragmencie „… w brzmieniu:” znajduje cytat „…”.
    Zwraca (cytat_bez_znaków_cytowania, indeks_za_zamykającym_cudzysłowem_i_opcjonalnym_;).
    """
    i = _skip_ws(s, start)
    if i >= len(s):
        return None
    if s[i] == _OPEN_QUOTE:
        i += 1
    elif s[i] in '"«':
        i += 1
    else:
        j = s.find(_OPEN_QUOTE, start)
        if j == -1:
            return None
        i = j + 1

    out: list[str] = []
    while i < len(s):
        ch = s[i]
        if ch == _CLOSE_QUOTE:
            body = "".join(out)
            i += 1
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == ";":
                i += 1
            return body, i
        if ch == "\n" and i + 1 < len(s):
            tail = s[i : i + 80]
            if re.match(
                r"\n\s*\d+\)\s*(?:w\s+(?:art\.|§|ust\.)|po\s+(?:art\.|ust\.)|uchyla\s+się)",
                tail,
                re.IGNORECASE,
            ):
                body = "".join(out)
                return body, i
        out.append(ch)
        i += 1
    return None


_RE_PO_ART_DOD_ART = re.compile(
    r"(?is)(?P<head>po\s+art\.\s*(?P<a1>\d+[a-z]*)\s+dodaje\s+się\s+art\.\s*(?P<a2>\d+[a-z]*)\s+w\s+brzmieniu\s*:)",
    re.UNICODE,
)

_RE_NUM_W_ART_PO_UST = re.compile(
    r"(?is)(?P<head>^\s*(?P<num>\d+)\)\s*w\s+art\.\s*(?P<art>\d+[a-z]*)\s+po\s+ust\.\s*(?P<u0>\d+[a-z]*)\s+"
    r"dodaje\s+się\s+ust\.\s*(?P<u1>\d+[a-z]*)\s+w\s+brzmieniu\s*:)",
    re.MULTILINE | re.UNICODE,
)


def extract_fragments(text: str) -> list[ChangeFragment]:
    found: list[tuple[int, ChangeFragment]] = []

    for m in _RE_PO_ART_DOD_ART.finditer(text):
        q = _extract_quote_after_brzmieniu(text, m.end())
        if not q:
            continue
        body, end = q
        full = text[m.start() : end].strip()
        frag = ChangeFragment(
            rodzaj="po_art_dodaje_art",
            surowy_nagłówek=m.group("head").strip(),
            cytat=body.strip(),
            pełny_tekst=full,
            pola={
                "po_artykule": m.group("a1"),
                "dodawany_artykuł": m.group("a2"),
            },
        )
        found.append((m.start(), frag))

    for m in _RE_NUM_W_ART_PO_UST.finditer(text):
        q = _extract_quote_after_brzmieniu(text, m.end())
        if not q:
            continue
        body, end = q
        full = text[m.start() : end].strip()
        frag = ChangeFragment(
            rodzaj="numerowany_w_art_po_ust_dodaje_ust",
            surowy_nagłówek=re.sub(r"\s+", " ", m.group("head").strip()),
            cytat=body.strip(),
            pełny_tekst=full,
            pola={
                "numer_punktu": int(m.group("num")),
                "artykuł": m.group("art"),
                "kotwica_ustępu": m.group("u0"),
                "dodawany_ustęp": m.group("u1"),
            },
        )
        found.append((m.start(), frag))

    found.sort(key=lambda x: x[0])
    return [f for _, f in found]


def fragments_to_zmiany(frags: list[ChangeFragment]) -> list[dict[str, Any]]:
    """
    Mapuje fragmenty na elementy listy ``zmiany`` w tym samym zbiorze pól co
    ``classify_fragment`` (``paragraf``, ``ustęp``, ``punkt``, ``kotwica_ustępu``,
    ``rodzaj``, ``tekst`` oraz opcjonalnie ``artykuł``).
    """
    out: list[dict[str, Any]] = []
    for f in frags:
        if f.rodzaj == "po_art_dodaje_art":
            out.append(
                {
                    "paragraf": f.pola["po_artykule"],
                    "ustęp": f.pola["dodawany_artykuł"],
                    "punkt": "",
                    "kotwica_ustępu": "",
                    "rodzaj": "dodanie_artykulu_po_artykule",
                    "tekst": f.pełny_tekst[:50000],
                }
            )
        elif f.rodzaj == "numerowany_w_art_po_ust_dodaje_ust":
            out.append(
                {
                    "paragraf": "",
                    "ustęp": f.pola["dodawany_ustęp"],
                    "punkt": "",
                    "kotwica_ustępu": f.pola["kotwica_ustępu"],
                    "rodzaj": "po_ustępie_dodanie_ustępu",
                    "artykuł": f.pola["artykuł"],
                    "tekst": f.pełny_tekst[:50000],
                }
            )
    return out


def run_fragment(
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

        frags = extract_fragments(text)
        zmiany = fragments_to_zmiany(frags)

        if not zmiany:
            logging.info("Brak wykrytych fragmentów — pominięto zapis do changes: %s", doc.get("address"))
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
            "Zapisano (fragment): %s -> zmieniany %s, fragmentów: %s",
            doc.get("address"),
            amended_payload.get("ELI") or "nie rozpoznano",
            len(zmiany),
        )

    client.close()
    logging.info("Przetworzono dokumentów: %s", processed)
    return 0


def _load_text(args: argparse.Namespace) -> str:
    if args.text_file:
        return args.text_file.read_text(encoding="utf-8")
    if args.string is not None:
        return args.string
    return sys.stdin.read()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=(
            "PDF z isap → fragmenty „po art. … w brzmieniu:” / „N) w art. … po ust. …” "
            "→ ta sama kolekcja MongoDB ``changes`` co ``isap_extract_changes.py`` "
            "(``--no-mongo``: tylko ekstrakcja z tekstu)."
        )
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
    p.add_argument(
        "--no-mongo",
        action="store_true",
        help="Nie łącz z MongoDB — wypisz fragmenty z --text-file / --string / stdin",
    )
    p.add_argument("--text-file", type=argparse.FileType("r", encoding="utf-8"))
    p.add_argument("--string", type=str, default=None, help="Tekst wejściowy (tylko z --no-mongo)")
    p.add_argument("--json", action="store_true", help="Przy --no-mongo: wypisz JSON")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    logging.getLogger("pymongo").setLevel(logging.WARNING)

    if args.no_mongo:
        if args.text_file is None and args.string is None and sys.stdin.isatty():
            p.error("Przy --no-mongo podaj --text-file, --string albo przekaż tekst na stdin.")
        text = _load_text(args)
        frags = extract_fragments(text)
        if args.json:
            print(json.dumps([asdict(f) for f in frags], ensure_ascii=False, indent=2))
        else:
            for i, f in enumerate(frags, 1):
                print(f"--- Fragment {i} ({f.rodzaj}) ---")
                print(f"Pola: {f.pola}")
                print(f"Nagłówek: {f.surowy_nagłówek}")
                print(f"Cytat ({len(f.cytat)} znaków):")
                print(f.cytat[:2000] + ("…" if len(f.cytat) > 2000 else ""))
                print()
        return 0

    try:
        return run_fragment(
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


# dla testu: `python isap_extract_changes_fragment.py` z przykładową stałą
_PRZYKŁAD = r"""
13) po art. 9a dodaje się art. 9aa w brzmieniu:
„Art. 9aa. 1. Maksymalna utrata generacji mocy czynnej z jednostki wytwórczej nie może przekraczać największej
mocy przyłączeniowej określonej dla niepodzielnego synchronicznego modułu wytwarzania energii w warunkach
przyłączenia do sieci przesyłowej elektroenergetycznej oraz koordynowanej sieci 110 kV. Operator systemu przesyło-
wego elektroenergetycznego określa w instrukcji, o której mowa w art. 9g ust. 1:
1) wartość maksymalnej utraty generacji mocy czynnej,
2) datę, od której ta wartość obowiązuje
– biorąc pod uwagę bezpieczeństwo i niezawodne funkcjonowanie krajowego systemu elektroenergetycznego.
2. Wytwórca stosuje rozwiązania techniczne zapewniające spełnienie wymagań przez jednostkę wytwórczą.”;

3) w art. 4j po ust. 3a dodaje się ust. 3b w brzmieniu: 
„3b. Sprzedawca energii elektrycznej lub paliw gazowych wskazuje odbiorcy, o którym mowa w ust. 3a, maksy-
malną wysokość kary umownej, która nie może przekroczyć wartości bezpośrednich strat ekonomicznych poniesionych 
przez sprzedawcę oraz sposób wyliczenia tych strat.”; 
4) inny punkt.
"""


if __name__ == "__main__":
    if len(sys.argv) == 1:
        frags = extract_fragments(_PRZYKŁAD)
        print(json.dumps([asdict(f) for f in frags], ensure_ascii=False, indent=2))
        raise SystemExit(0)
    raise SystemExit(main(sys.argv[1:]))
