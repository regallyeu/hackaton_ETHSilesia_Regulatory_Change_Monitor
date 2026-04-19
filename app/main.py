"""
Minimal API for hackathon.

Run (from hackaton_ETHSilesia directory, active venv):
  uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import math
import os
import re
import uuid as _uuid
import xml.etree.ElementTree as _ET
import zipfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path as FsPath
from typing import Any

import httpx
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from blockchain.anchors import AlertAnchorRequest, get_anchor_backend

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MongoDB
# ---------------------------------------------------------------------------

_mongo_client = None


def _get_db():
    global _mongo_client
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        return None
    if _mongo_client is None:
        from pymongo import MongoClient
        _mongo_client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    return _mongo_client[os.environ.get("ISAP_MONGO_DB", "legal_acts")]


def _str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v) or fallback
    return str(value)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _risk_from_zmiany(zmiany: list) -> int:
    n = len(zmiany)
    return min(max(n * 2, 3), 9)


_ISAP_TYPE_TO_CHANGE_TYPE = {
    "Ustawa": "new_regulation",
    "Rozporządzenie": "new_regulation",
    "Rozporządzenie z mocą ustawy": "new_regulation",
    "Obwieszczenie": "guidance",
    "Komunikat": "guidance",
    "Ogłoszenie": "guidance",
    "Zarządzenie": "guidance",
    "Uchwała": "amendment",
    "Decyzja": "amendment",
}


def _build_alert_dict(isap_doc: dict[str, Any], change_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    act = (change_doc or {}).get("akt_zmieniający") or {} if change_doc else {}
    address = isap_doc.get("address") or act.get("address") or str((change_doc or {}).get("_id", ""))
    eli = isap_doc.get("ELI") or act.get("ELI") or ""
    doc_type = _str(isap_doc.get("type"))
    in_force = isap_doc.get("inForce", "")
    display = _str(isap_doc.get("displayAddress"))
    status_raw = _str(isap_doc.get("status"))
    keywords = _str(isap_doc.get("keywords"))
    title = _str(isap_doc.get("title")) or act.get("tytuł") or address

    change_type = _ISAP_TYPE_TO_CHANGE_TYPE.get(doc_type, "amendment")
    risk_level = 7 if in_force == "IN_FORCE" else 5
    parts = [p for p in [doc_type, status_raw, keywords] if p]
    summary = f"{display} — {', '.join(parts)}" if parts else display or "Brak opisu."
    zmiany_out: list[dict[str, Any]] = []

    if change_doc:
        amended = change_doc.get("akt_zmieniany") or {}
        zmiany_raw = change_doc.get("zmiany") or []
        n = len(zmiany_raw)
        amended_title = amended.get("tytuł") or amended.get("ELI") or "nieznany akt"
        if n == 1:
            suffix = "fragment"
        elif 2 <= n <= 4:
            suffix = "fragmenty"
        else:
            suffix = "fragmentów"
        first_tekst = zmiany_raw[0].get("tekst", "") if zmiany_raw else ""
        snippet = (first_tekst[:200] + "…") if len(first_tekst) > 200 else first_tekst
        summary = f"Zmienia: {amended_title}. Wykryto {n} {suffix} zmian."
        if snippet:
            summary += f" Fragment: {snippet}"
        risk_level = _risk_from_zmiany(zmiany_raw)
        change_type = "amendment"
        zmiany_out = [
            {
                "rodzaj": z.get("rodzaj", ""),
                "tekst": z.get("tekst", ""),
                "artykuł": z.get("artykuł", ""),
                "sekcja": z.get("sekcja", ""),
                "ustęp": z.get("ustęp", ""),
                "punkt": z.get("punkt", ""),
            }
            for z in zmiany_raw
        ]

    keywords_out = [str(k) for k in (isap_doc.get("keywords") or []) if k]
    keywords_names_out = [str(k) for k in (isap_doc.get("keywordsNames") or []) if k]

    directives_out = [
        {
            "address": d.get("address", ""),
            "date": d.get("date"),
            "title": d.get("title", ""),
        }
        for d in (isap_doc.get("directives") or [])
        if d.get("address")
    ]

    refs = isap_doc.get("references") or {}
    legal_bases_out = [
        {"id": r.get("id", ""), "art": r.get("art", "")}
        for r in (refs.get("Podstawa prawna") or [])
        if r.get("id")
    ]

    amended_act_out = None
    if change_doc:
        amended = change_doc.get("akt_zmieniany") or {}
        if amended.get("address") or amended.get("ELI"):
            amended_act_out = {
                "address": amended.get("address"),
                "eli": amended.get("ELI"),
                "title": amended.get("tytuł"),
            }

    return {
        "id": address,
        "title": title,
        "summary": summary,
        "source_url": f"https://api.sejm.gov.pl/eli/acts/{eli}" if eli else None,
        "anchor": None,
        "source": "ISAP",
        "document_id": address,
        "detected_at": _iso(isap_doc.get("crawledAt")),
        "published_at": _str(isap_doc.get("announcementDate")) or None,
        "status": "new",
        "change_type": change_type,
        "risk_level": risk_level,
        "zmiany": zmiany_out,
        "directives": directives_out,
        "keywords": keywords_out,
        "keywords_names": keywords_names_out,
        "legal_bases": legal_bases_out,
        "amended_act": amended_act_out,
    }


def _get_alerts_page(page: int, limit: int) -> tuple[list[dict[str, Any]], int]:
    db = _get_db()
    if db is None:
        return [], 0
    try:
        isap = db[os.environ.get("ISAP_MONGO_COLLECTION", "isap")]
        changes = db[os.environ.get("ISAP_CHANGES_COLLECTION", "changes")]

        query = {"wykryto_blok_zmian": True}
        total = changes.count_documents(query)
        skip = (page - 1) * limit
        change_docs = list(changes.find(query).sort("analyzedAt", -1).skip(skip).limit(limit))

        addresses = [
            (c.get("akt_zmieniający") or {}).get("address")
            for c in change_docs
        ]
        addresses = [a for a in addresses if a]
        isap_map: dict[str, Any] = {
            d["address"]: d
            for d in isap.find({"address": {"$in": addresses}})
            if d.get("address")
        }

        results = [
            _build_alert_dict(
                isap_map.get((c.get("akt_zmieniający") or {}).get("address") or "", {}),
                c,
            )
            for c in change_docs
        ]
        return results, total
    except Exception as exc:
        log.warning("MongoDB query failed: %s", exc)
        return [], 0


def _demo_alert_dict(alert_id: str) -> dict[str, Any] | None:
    for d in _DEMO_ALERTS:
        if d["id"] != alert_id:
            continue
        return {
            "id": d["id"],
            "title": d["title"],
            "summary": d["summary"],
            "source_url": d.get("source_url"),
            "anchor": d.get("anchor"),
            "source": "ISAP",
            "document_id": d["id"],
            "detected_at": None,
            "published_at": None,
            "status": "new",
            "change_type": "amendment",
            "risk_level": 7,
            "zmiany": [],
            "related_changes": [],
            "directives": [],
            "keywords": [],
            "keywords_names": [],
            "legal_bases": [],
            "amended_act": None,
        }
    return None


def _get_alert_by_id(alert_id: str) -> dict[str, Any] | None:
    db = _get_db()
    if db is None:
        return _demo_alert_dict(alert_id)
    try:
        isap = db[os.environ.get("ISAP_MONGO_COLLECTION", "isap")]
        changes = db[os.environ.get("ISAP_CHANGES_COLLECTION", "changes")]

        change = changes.find_one({"akt_zmieniający.address": alert_id, "wykryto_blok_zmian": True})
        if not change:
            return _demo_alert_dict(alert_id)
        isap_doc = isap.find_one({"address": alert_id}) or {}
        result = _build_alert_dict(isap_doc, change)

        amended_address = (change.get("akt_zmieniany") or {}).get("address")
        if amended_address:
            related_docs = list(
                changes.find(
                    {"akt_zmieniany.address": amended_address, "wykryto_blok_zmian": True},
                    sort=[("analyzedAt", 1)],
                )
            )
            result["related_changes"] = [
                {
                    "id": (r.get("akt_zmieniający") or {}).get("address") or str(r["_id"]),
                    "title": (r.get("akt_zmieniający") or {}).get("tytuł") or "",
                    "analyzed_at": _iso(r.get("analyzedAt")),
                    "zmiany_count": len(r.get("zmiany") or []),
                }
                for r in related_docs
            ]

        return result
    except Exception as exc:
        log.warning("MongoDB query failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Anchor store (in-memory, anchored tx references)
# ---------------------------------------------------------------------------

_anchors: dict[str, dict[str, Any]] = {}
_read_receipts: dict[str, list[dict[str, Any]]] = {}
_documents: dict[str, dict[str, Any]] = {}
UPLOADS_DIR = FsPath(os.environ.get("UPLOADS_DIR", "uploads"))

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _canonical_payload(alert: dict[str, Any]) -> bytes:
    blob = {
        "id": alert["id"],
        "title": alert["title"],
        "summary": alert["summary"],
        "source_url": alert.get("source_url"),
    }
    return json.dumps(blob, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _content_hash(alert: dict[str, Any]) -> bytes:
    return hashlib.sha256(_canonical_payload(alert)).digest()


class AnchorReceiptJson(BaseModel):
    backend: str
    chain_id: str
    tx_reference: str
    block_number: int | None = None
    explorer_url: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ZmianaJson(BaseModel):
    rodzaj: str = ""
    tekst: str = ""
    artykuł: str = ""
    sekcja: str = ""
    ustęp: str = ""
    punkt: str = ""


class DirectiveJson(BaseModel):
    address: str
    date: str | None = None
    title: str = ""


class LegalBaseJson(BaseModel):
    id: str
    art: str = ""


class AmendedActJson(BaseModel):
    address: str | None = None
    eli: str | None = None
    title: str | None = None


class RelatedChangeJson(BaseModel):
    id: str
    title: str
    analyzed_at: str | None = None
    zmiany_count: int = 0


class ReadReceiptRequest(BaseModel):
    """Optional stable pseudonym for the viewer (e.g. client-generated UUID in localStorage)."""

    reader_ref: str | None = None


class ReadReceiptJson(BaseModel):
    read_at: str
    reader_ref: str | None = None
    anchor: AnchorReceiptJson


class AlertJson(BaseModel):
    id: str
    title: str
    summary: str
    source_url: str | None = None
    anchor: AnchorReceiptJson | None = None
    read_receipts: list[ReadReceiptJson] = Field(default_factory=list)
    source: str = "ISAP"
    document_id: str | None = None
    detected_at: str | None = None
    published_at: str | None = None
    status: str = "new"
    change_type: str = "amendment"
    risk_level: int = 5
    zmiany: list[ZmianaJson] = Field(default_factory=list)
    related_changes: list[RelatedChangeJson] = Field(default_factory=list)
    directives: list[DirectiveJson] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    keywords_names: list[str] = Field(default_factory=list)
    legal_bases: list[LegalBaseJson] = Field(default_factory=list)
    amended_act: AmendedActJson | None = None


class ContractJson(BaseModel):
    id: str
    name: str
    counterparty: str
    type: str
    valid_until: str
    alert_count: int


_CONTRACTS_SEED: list[dict[str, Any]] = [
    {
        "id": "contract-001",
        "name": "PPA z WindFarm Sp. z o.o.",
        "counterparty": "WindFarm Sp. z o.o.",
        "type": "PPA",
        "valid_until": "2030-12-31",
        "alert_count": 2,
    },
    {
        "id": "contract-002",
        "name": "PPA z SolarTech S.A.",
        "counterparty": "SolarTech S.A.",
        "type": "PPA",
        "valid_until": "2028-06-30",
        "alert_count": 1,
    },
    {
        "id": "contract-003",
        "name": "Przyłączenie sieci — Operator SA",
        "counterparty": "Operator SA",
        "type": "grid_connection",
        "valid_until": "2035-12-31",
        "alert_count": 0,
    },
]


class PaginatedAlerts(BaseModel):
    items: list[AlertJson]
    total: int
    page: int
    pages: int


_DEMO_ALERTS = [
    {
        "id": "demo-red-001",
        "title": "Nowelizacja RED III (przykład)",
        "summary": "Wykryto zmianę w zakresie certyfikacji — mapowanie na klauzule PPA.",
        "source_url": "https://eur-lex.europa.eu/",
        "anchor": None,
    },
    {
        "id": "demo-ure-002",
        "title": "URE — zmiana taryfy (przykład)",
        "summary": "Akt pomocniczy; ryzyko średnie dla kontraktu dystrybucyjnego.",
        "source_url": "https://www.ure.gov.pl/",
        "anchor": None,
    },
]


def _build_alert_json(alert: dict[str, Any]) -> AlertJson:
    anchor_data = _anchors.get(alert["id"]) or alert.get("anchor")
    anchor_model = AnchorReceiptJson(**anchor_data) if anchor_data else None
    receipts: list[ReadReceiptJson] = []
    for r in _read_receipts.get(alert["id"], []):
        ad = r.get("anchor") or {}
        receipts.append(
            ReadReceiptJson(
                read_at=r["read_at"],
                reader_ref=r.get("reader_ref"),
                anchor=AnchorReceiptJson(**ad),
            )
        )
    return AlertJson(
        id=alert["id"],
        title=alert["title"],
        summary=alert["summary"],
        source_url=alert.get("source_url"),
        anchor=anchor_model,
        read_receipts=receipts,
        source=alert.get("source", "ISAP"),
        document_id=alert.get("document_id"),
        detected_at=alert.get("detected_at"),
        published_at=alert.get("published_at"),
        status=alert.get("status", "new"),
        change_type=alert.get("change_type", "amendment"),
        risk_level=alert.get("risk_level", 5),
        zmiany=[ZmianaJson(**z) for z in alert.get("zmiany", [])],
        related_changes=[RelatedChangeJson(**r) for r in alert.get("related_changes", [])],
        directives=[DirectiveJson(**d) for d in alert.get("directives", [])],
        keywords=alert.get("keywords", []),
        keywords_names=alert.get("keywords_names", []),
        legal_bases=[LegalBaseJson(**b) for b in alert.get("legal_bases", [])],
        amended_act=AmendedActJson(**alert["amended_act"]) if alert.get("amended_act") else None,
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    global _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None


app = FastAPI(title="Regulatory Change Monitor API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExpiringActJson(BaseModel):
    address: str
    title: str
    expiration_date: str


class StatsJson(BaseModel):
    total: int
    high_risk: int
    pending_review: int
    resolved_this_month: int
    last_analyzed_at: str | None = None
    in_force_count: int = 0
    expiring_soon_count: int = 0
    expiring_soon: list[ExpiringActJson] = Field(default_factory=list)


@app.get("/contracts", response_model=list[ContractJson])
def list_contracts() -> list[ContractJson]:
    return [ContractJson(**c) for c in _CONTRACTS_SEED]


@app.get("/stats", response_model=StatsJson)
def get_stats() -> StatsJson:
    db = _get_db()
    if db is None:
        return StatsJson(total=0, high_risk=0, pending_review=0, resolved_this_month=0)
    try:
        changes = db[os.environ.get("ISAP_CHANGES_COLLECTION", "changes")]
        query = {"wykryto_blok_zmian": True}
        total = changes.count_documents(query)
        # risk_level = min(max(len(zmiany)*2, 3), 9) → risk>=7 when len>=4
        high_risk = changes.count_documents({**query, "zmiany.3": {"$exists": True}})
        latest = changes.find_one(query, sort=[("analyzedAt", -1)], projection={"analyzedAt": 1})
        last_at = _iso(latest.get("analyzedAt")) if latest else None

        isap = db[os.environ.get("ISAP_MONGO_COLLECTION", "isap")]
        in_force_count = isap.count_documents({"inForce": "IN_FORCE"})
        today_str = date.today().isoformat()
        in_30_str = (date.today() + timedelta(days=30)).isoformat()
        expiring_cursor = isap.find(
            {"expirationDate": {"$gte": today_str, "$lte": in_30_str}},
            sort=[("expirationDate", 1)],
            limit=10,
        )
        expiring_list = [
            ExpiringActJson(
                address=d.get("address", str(d["_id"])),
                title=_str(d.get("title"), fallback=d.get("address", "")),
                expiration_date=d.get("expirationDate", ""),
            )
            for d in expiring_cursor
        ]
        return StatsJson(
            total=total,
            high_risk=high_risk,
            pending_review=total,
            resolved_this_month=0,
            last_analyzed_at=last_at,
            in_force_count=in_force_count,
            expiring_soon_count=len(expiring_list),
            expiring_soon=expiring_list,
        )
    except Exception as exc:
        log.warning("MongoDB stats failed: %s", exc)
        return StatsJson(total=0, high_risk=0, pending_review=0, resolved_this_month=0)


@app.get("/alerts", response_model=PaginatedAlerts)
def list_alerts(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
) -> PaginatedAlerts:
    alerts, total = _get_alerts_page(page, limit)
    if not alerts and total == 0:
        demo = _DEMO_ALERTS
        return PaginatedAlerts(
            items=[_build_alert_json(a) for a in demo],
            total=len(demo),
            page=1,
            pages=1,
        )
    pages = max(1, math.ceil(total / limit))
    return PaginatedAlerts(
        items=[_build_alert_json(a) for a in alerts],
        total=total,
        page=page,
        pages=pages,
    )


@app.get("/alerts/{alert_id}", response_model=AlertJson)
def get_alert(alert_id: str) -> AlertJson:
    alert = _get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _build_alert_json(alert)


@app.post("/alerts/{alert_id}/anchor", response_model=AlertJson)
def anchor_alert(alert_id: str) -> AlertJson:
    alert = _get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    content_hash = _content_hash(alert)
    backend_anchor = get_anchor_backend()
    receipt = backend_anchor.anchor(
        AlertAnchorRequest(alert_id=alert_id, content_hash=content_hash)
    )
    _anchors[alert_id] = {
        "backend": receipt.backend,
        "chain_id": receipt.chain_id,
        "tx_reference": receipt.tx_reference,
        "block_number": receipt.block_number,
        "explorer_url": receipt.explorer_url,
        "extra": dict(receipt.extra),
    }
    return _build_alert_json(alert)


@app.post("/alerts/{alert_id}/read-receipt", response_model=ReadReceiptJson)
def record_alert_read_receipt(
    alert_id: str,
    body: ReadReceiptRequest | None = Body(default=None),
) -> ReadReceiptJson:
    """Anchor a read event (who/when opened the alert) for audit and compliance."""
    alert = _get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    req = body or ReadReceiptRequest()
    read_at = datetime.now(timezone.utc).isoformat()
    ref = (req.reader_ref or "").strip() or None
    canonical = json.dumps(
        {"alert_id": alert_id, "read_at": read_at, "reader_ref": ref},
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    content_hash = hashlib.sha256(canonical).digest()
    rid = f"read:{alert_id}:{_uuid.uuid4().hex[:16]}"
    backend_anchor = get_anchor_backend()
    receipt = backend_anchor.anchor(AlertAnchorRequest(alert_id=rid, content_hash=content_hash))
    entry = {
        "read_at": read_at,
        "reader_ref": ref,
        "anchor": {
            "backend": receipt.backend,
            "chain_id": receipt.chain_id,
            "tx_reference": receipt.tx_reference,
            "block_number": receipt.block_number,
            "explorer_url": receipt.explorer_url,
            "extra": dict(receipt.extra),
        },
    }
    _read_receipts.setdefault(alert_id, []).append(entry)
    return ReadReceiptJson(
        read_at=entry["read_at"],
        reader_ref=entry["reader_ref"],
        anchor=AnchorReceiptJson(**entry["anchor"]),
    )


# ---------------------------------------------------------------------------
# ISAP acts browser
# ---------------------------------------------------------------------------


class IsapActJson(BaseModel):
    address: str
    title: str
    doc_type: str = ""
    status: str = ""
    in_force: str = ""
    announcement_date: str | None = None
    expiration_date: str | None = None
    eli: str | None = None
    display_address: str = ""
    keywords: list[str] = Field(default_factory=list)
    keywords_names: list[str] = Field(default_factory=list)
    source_url: str | None = None


class PaginatedIsap(BaseModel):
    items: list[IsapActJson]
    total: int
    page: int
    pages: int


def _build_isap_json(doc: dict[str, Any]) -> IsapActJson:
    address = doc.get("address", str(doc.get("_id", "")))
    eli = doc.get("ELI") or None
    return IsapActJson(
        address=address,
        title=_str(doc.get("title"), fallback=address),
        doc_type=_str(doc.get("type")),
        status=_str(doc.get("status")),
        in_force=_str(doc.get("inForce")),
        announcement_date=_str(doc.get("announcementDate")) or None,
        expiration_date=_str(doc.get("expirationDate")) or None,
        eli=eli,
        display_address=_str(doc.get("displayAddress")),
        keywords=[str(k) for k in (doc.get("keywords") or []) if k],
        keywords_names=[str(k) for k in (doc.get("keywordsNames") or []) if k],
        source_url=f"https://api.sejm.gov.pl/eli/acts/{eli}" if eli else None,
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class ProposalJson(BaseModel):
    id: str
    original_text: str
    proposed_text: str
    reason: str
    status: str = "pending"
    edited_text: str | None = None


class DocumentJson(BaseModel):
    id: str
    alert_id: str
    filename: str
    uploaded_at: str
    status: str = "draft"
    proposals: list[ProposalJson] = Field(default_factory=list)
    signed_tx_hash: str | None = None
    signed_at: str | None = None


class UpdateProposalRequest(BaseModel):
    status: str
    edited_text: str | None = None


def _extract_docx_text(data: bytes) -> str:
    _WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml_bytes = z.read("word/document.xml")
        root = _ET.fromstring(xml_bytes)
        paragraphs: list[str] = []
        for para in root.iter(f"{_WNS}p"):
            runs = [node.text for node in para.iter(f"{_WNS}t") if node.text]
            if runs:
                paragraphs.append("".join(runs))
        return "\n".join(paragraphs)
    except Exception as exc:
        log.warning("DOCX extraction failed: %s", exc)
        return ""


def _extract_text(path: FsPath, filename: str) -> str:
    try:
        if filename.lower().endswith(".pdf"):
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            return "\n".join(page.get_text() for page in doc)
        if filename.lower().endswith((".docx", ".doc")):
            return _extract_docx_text(path.read_bytes())
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        log.warning("Text extraction failed for %s: %s", filename, exc)
        return ""



def _extract_normative_text(tekst: str, art: str = "", rodzaj: str = "") -> str:
    """Wyciąga właściwy tekst normatywny z opisu proceduralnego zmiany."""
    # "otrzymuje brzmienie: „nowy tekst""
    m = re.search(
        r'(?:otrzymuje(?:ją)?\s+brzmienie|w\s+brzmieniu)\s*:?\s*\n?\s*[„"](.+?)(?=[""]\s*[;,"\n]|\Z)',
        tekst, re.DOTALL | re.IGNORECASE,
    )
    if m and len(m.group(1).strip()) > 30:
        prefix = f"Art. {art} – nowe brzmienie:\n" if art else "Nowe brzmienie:\n"
        return prefix + m.group(1).strip()

    # "zastępuje się wyrazami «nowy»"
    m = re.search(
        r'zastępuje się wyrazami\s*[„«"](.+?)[»""„]',
        tekst, re.DOTALL | re.IGNORECASE,
    )
    if m and len(m.group(1).strip()) > 5:
        prefix = f"Art. {art} – zmienione wyrażenie:\n" if art else "Zmienione wyrażenie:\n"
        return prefix + m.group(1).strip()

    # uchylenie artykułu
    if re.search(r'uchyla się', tekst, re.IGNORECASE):
        art_ref = f"Art. {art}" if art else "Artykuł"
        return (
            f"{art_ref} zostaje uchylony. "
            "Umowa nie powinna odwoływać się do tego przepisu ani na nim bazować."
        )

    return tekst  # fallback — pełny tekst


def _build_single_ustawa(z: dict[str, Any], title: str) -> str:
    """Buduje tekst ustawa dla jednej zmiany."""
    tekst = (z.get("tekst") or "").strip()
    if not tekst:
        return ""
    art = z.get("artykuł") or ""
    rodzaj = z.get("rodzaj") or ""
    normative = _extract_normative_text(tekst, art, rodzaj)
    parts: list[str] = []
    if title:
        parts.append(f"AKT PRAWNY: {title}")
    if rodzaj:
        parts.append(f"RODZAJ ZMIANY: {rodzaj}")
    parts.append(f"\nZMIANA W PRZEPISIE:\n{normative}")
    return "\n".join(parts)


async def _call_rag_single(
    ustawa: str,
    send_name: str,
    send_content: bytes,
    send_ct: str,
    zmiana_label: str,
) -> list[dict[str, Any]]:
    """Jedno wywołanie RAG dla jednej zmiany. Zwraca propozycje z ryzyko > 0."""
    base = _rag_base_url()
    files = {"file": (send_name, send_content, send_ct)}
    data = {"ustawa": ustawa}
    log.warning("RAG cycle [%s]: ustawa_chars=%d", zmiana_label, len(ustawa))
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(f"{base}/compliance/full-file", data=data, files=files)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        log.warning("RAG cycle [%s] unreachable: %s", zmiana_label, exc)
        return []
    if r.status_code >= 400:
        log.warning("RAG cycle [%s] error %d: %s", zmiana_label, r.status_code, r.text[:200])
        return []
    try:
        body = r.json()
    except Exception:
        return []
    assessments = body.get("answer") or []
    log.warning("RAG cycle [%s]: %d assessments", zmiana_label, len(assessments))
    proposals: list[dict[str, Any]] = []
    for a in assessments:
        if not isinstance(a, dict):
            continue
        ryzyko = int(a.get("ryzyko") or 0)
        if ryzyko == 0:
            continue
        proposals.append({
            "id": str(_uuid.uuid4()),
            "original_text": a.get("brzmienie_oryginalne") or "[Brak tekstu]",
            "proposed_text": a.get("brzmienie_poprawione") or "",
            "reason": f"[{a.get('status', '')}] {a.get('komentarz', '')} (ryzyko: {ryzyko}/100)",
            "status": "pending",
            "edited_text": None,
            "_ryzyko": ryzyko,
            "_zmiana": zmiana_label,
        })
    return proposals


async def _run_parallel_rag(
    alert: dict[str, Any],
    file_content: bytes,
    filename: str,
    content_type: str,
) -> list[dict[str, Any]] | None:
    """Uruchamia równoległe wywołania RAG — jedno na każdą zmianę w alercie."""
    title = alert.get("title") or ""
    zmiany = [z for z in (alert.get("zmiany") or []) if (z.get("tekst") or "").strip()]
    if not zmiany:
        return None

    # Przygotuj zawartość pliku do wysyłki (konwersja docx raz)
    suffix = FsPath(filename).suffix.lower()
    if suffix in (".docx", ".doc"):
        extracted = _extract_docx_text(file_content)
        if not extracted.strip():
            return None
        send_name = FsPath(filename).stem + ".txt"
        send_content = extracted.encode("utf-8")
        send_ct = "text/plain"
    else:
        send_name = filename
        send_content = file_content
        send_ct = content_type

    log.warning("RAG parallel: %d zmian, plik=%s", len(zmiany), send_name)

    tasks = []
    for i, z in enumerate(zmiany):
        ustawa = _build_single_ustawa(z, title)
        if not ustawa.strip():
            continue
        art = z.get("artykuł") or str(i + 1)
        tasks.append(_call_rag_single(ustawa, send_name, send_content, send_ct, art))

    if not tasks:
        return None

    results: list[list[dict[str, Any]]] = await asyncio.gather(*tasks)

    # Agregacja: deduplikuj po original_text, zachowaj najwyższe ryzyko
    seen: dict[str, dict[str, Any]] = {}
    for batch in results:
        for p in batch:
            key = (p["original_text"] or "")[:120].strip().lower()
            existing = seen.get(key)
            if existing is None or p["_ryzyko"] > existing["_ryzyko"]:
                seen[key] = p

    all_proposals = sorted(seen.values(), key=lambda p: p["_ryzyko"], reverse=True)

    # Usuń pomocnicze pola przed zapisem
    for p in all_proposals:
        p.pop("_ryzyko", None)
        p.pop("_zmiana", None)

    if not all_proposals:
        return [{
            "id": str(_uuid.uuid4()),
            "original_text": "Analiza zakończona",
            "proposed_text": "",
            "reason": f"Przeanalizowano {len(zmiany)} zmian przepisów — brak niezgodności z dokumentem.",
            "status": "pending",
            "edited_text": None,
        }]

    log.warning("RAG parallel wynik: %d unikalnych propozycji", len(all_proposals))
    return all_proposals




def _doc_to_json(doc: dict[str, Any]) -> DocumentJson:
    return DocumentJson(
        id=doc["id"],
        alert_id=doc["alert_id"],
        filename=doc["filename"],
        uploaded_at=doc["uploaded_at"],
        status=doc["status"],
        proposals=[ProposalJson(**p) for p in doc["proposals"]],
        signed_tx_hash=doc.get("signed_tx_hash"),
        signed_at=doc.get("signed_at"),
    )


@app.post("/alerts/{alert_id}/documents", response_model=DocumentJson)
async def upload_document(alert_id: str, file: UploadFile = File(...)) -> DocumentJson:
    alert = _get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    doc_id = str(_uuid.uuid4())
    safe_name = "".join(c if c.isalnum() or c in "-._" else "_" for c in (file.filename or "upload"))
    dest = UPLOADS_DIR / f"{doc_id}_{safe_name}"
    content = await file.read()
    dest.write_bytes(content)
    zmiany = alert.get("zmiany") or []
    proposals = await _run_parallel_rag(
        alert=alert,
        file_content=content,
        filename=file.filename or safe_name,
        content_type=file.content_type or "application/octet-stream",
    )
    if proposals is None:
        proposals = []
    now = datetime.now(timezone.utc).isoformat()
    doc: dict[str, Any] = {
        "id": doc_id,
        "alert_id": alert_id,
        "filename": file.filename or safe_name,
        "file_path": str(dest),
        "uploaded_at": now,
        "status": "draft",
        "proposals": proposals,
        "signed_tx_hash": None,
        "signed_at": None,
    }
    _documents[doc_id] = doc
    return _doc_to_json(doc)


@app.get("/alerts/{alert_id}/documents", response_model=list[DocumentJson])
def list_alert_documents(alert_id: str) -> list[DocumentJson]:
    return [_doc_to_json(d) for d in _documents.values() if d["alert_id"] == alert_id]


@app.patch("/documents/{doc_id}/proposals/{proposal_id}", response_model=DocumentJson)
def update_proposal(doc_id: str, proposal_id: str, body: UpdateProposalRequest) -> DocumentJson:
    doc = _documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if body.status not in ("accepted", "rejected", "edited"):
        raise HTTPException(status_code=400, detail="status must be accepted | rejected | edited")
    for p in doc["proposals"]:
        if p["id"] == proposal_id:
            p["status"] = body.status
            if body.status == "edited":
                p["edited_text"] = body.edited_text
            break
    else:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if all(p["status"] != "pending" for p in doc["proposals"]) and doc["status"] == "draft":
        doc["status"] = "reviewed"
    return _doc_to_json(doc)


@app.post("/documents/{doc_id}/sign", response_model=DocumentJson)
def sign_document(doc_id: str) -> DocumentJson:
    doc = _documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc["status"] not in ("reviewed", "draft"):
        raise HTTPException(status_code=400, detail="All proposals must be answered before signing")
    content_hash = hashlib.sha256(
        f"{doc_id}:{doc['alert_id']}:{doc['filename']}".encode()
    ).digest()
    backend_anchor = get_anchor_backend()
    receipt = backend_anchor.anchor(
        AlertAnchorRequest(alert_id=doc_id, content_hash=content_hash)
    )
    doc["status"] = "signed"
    doc["signed_tx_hash"] = receipt.tx_reference
    doc["signed_at"] = datetime.now(timezone.utc).isoformat()
    return _doc_to_json(doc)


@app.get("/documents/{doc_id}/file", response_model=None)
def preview_document(doc_id: str) -> FileResponse | JSONResponse:
    doc = _documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = FsPath(doc["file_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return FileResponse(path, media_type="application/pdf", filename=doc["filename"])
    if suffix in (".docx", ".doc"):
        text = _extract_docx_text(path.read_bytes())
        return JSONResponse(content={"text": text or "(brak tekstu)"}, media_type="application/json")
    return FileResponse(path, media_type="text/plain; charset=utf-8", filename=doc["filename"])


@app.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str) -> None:
    doc = _documents.pop(doc_id, None)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        FsPath(doc["file_path"]).unlink(missing_ok=True)
    except Exception:
        pass


@app.get("/documents/signed", response_model=list[DocumentJson])
def list_signed_documents() -> list[DocumentJson]:
    return [_doc_to_json(d) for d in _documents.values() if d["status"] == "signed"]


@app.get("/documents/{doc_id}/download")
def download_document(doc_id: str) -> FileResponse:
    doc = _documents.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    file_path = FsPath(doc["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path=str(file_path), filename=doc["filename"], media_type="application/octet-stream")


@app.get("/isap", response_model=PaginatedIsap)
def list_isap(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    q: str = Query(default=""),
    in_force: str = Query(default=""),
    doc_type: str = Query(default=""),
) -> PaginatedIsap:
    db = _get_db()
    if db is None:
        return PaginatedIsap(items=[], total=0, page=1, pages=1)
    try:
        isap = db[os.environ.get("ISAP_MONGO_COLLECTION", "isap")]
        mongo_query: dict[str, Any] = {}
        if q:
            import re as _re
            pattern = _re.compile(_re.escape(q), _re.IGNORECASE)
            mongo_query["$or"] = [
                {"title": pattern},
                {"address": pattern},
                {"displayAddress": pattern},
                {"keywords": pattern},
            ]
        if in_force:
            mongo_query["inForce"] = in_force
        if doc_type:
            mongo_query["type"] = doc_type
        total = isap.count_documents(mongo_query)
        skip = (page - 1) * limit
        docs = list(isap.find(mongo_query).sort("announcementDate", -1).skip(skip).limit(limit))
        pages = max(1, math.ceil(total / limit))
        return PaginatedIsap(
            items=[_build_isap_json(d) for d in docs],
            total=total,
            page=page,
            pages=pages,
        )
    except Exception as exc:
        log.warning("MongoDB isap query failed: %s", exc)
        return PaginatedIsap(items=[], total=0, page=1, pages=1)


# ---------------------------------------------------------------------------
# RAG (osobny serwis qdrant_basic — proxy pod jednym Swaggerem na :8000)
# ---------------------------------------------------------------------------


def _rag_base_url() -> str:
    return os.environ.get("RAG_SERVICE_URL", "http://127.0.0.1:8080").rstrip("/")


def _rag_unreachable_detail(url: str) -> str:
    return (
        f"Nie można połączyć z RAG pod {url}. "
        "W kontenerze Docker 127.0.0.1 to localhost TEGO kontenera — nie zobaczysz RAG na hoście. "
        "Ustaw RAG_SERVICE_URL=http://host.docker.internal:8080 (Docker Desktop Windows/Mac) albo nazwę serwisu w sieci Docker. "
        "Gdy API i RAG są uruchomione lokalnie na maszynie (bez Dockera API): http://127.0.0.1:8080."
    )


@app.get("/rag/health", tags=["rag"])
async def rag_health_proxy() -> JSONResponse:
    """Stan Qdranta / RAG z serwisu qdrant_basic (musi działać na RAG_SERVICE_URL)."""
    url = f"{_rag_base_url()}/health"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail=_rag_unreachable_detail(url)) from exc
    return JSONResponse(status_code=r.status_code, content=r.json() if r.content else {})


@app.post(
    "/rag/compliance/full-file",
    tags=["rag"],
    summary="Pełna UMOWA z pliku vs USTAWA (LLM) — proxy do qdrant_basic",
    operation_id="compliance_full_file",
)
async def rag_compliance_full_file_proxy(
    ustawa: str = Form(
        ...,
        min_length=1,
        description="Fragment lub treść USTAWY (norma), np. wklejony artykuł z ISAP",
    ),
    file: UploadFile = File(..., description="Plik UMOWY: .pdf, .txt, .md"),
) -> JSONResponse:
    """
    Przekazuje żądanie do serwisu RAG (``POST /compliance/full-file``).
    W Swaggerze na http://localhost:8000/docs wybierasz plik PDF i wklejasz ``ustawa``.
    """
    base = _rag_base_url()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Pusty plik")
    safe_name = file.filename or "upload.pdf"
    files = {"file": (safe_name, content, file.content_type or "application/octet-stream")}
    data = {"ustawa": ustawa}
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            r = await client.post(f"{base}/compliance/full-file", data=data, files=files)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail=_rag_unreachable_detail(base)) from exc
    try:
        body: Any = r.json()
    except json.JSONDecodeError:
        body = {"detail": r.text or r.reason_phrase}
    if r.status_code >= 400:
        return JSONResponse(
            status_code=r.status_code,
            content=body if isinstance(body, dict) else {"detail": str(body)},
        )
    return JSONResponse(status_code=200, content=body)
