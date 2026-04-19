"""
HTTP API (OpenAPI / Swagger) dla RAG z Qdrantem — te same funkcje co w ``main.py``.

Uruchomienie lokalnie (z katalogu ``qdrant_basic``)::

  uvicorn api:app --reload --host 0.0.0.0 --port 8080

Dokumentacja interaktywna: http://localhost:8080/docs (Swagger), /redoc (ReDoc).
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, ValidationError

try:
    from . import main as rag
except ImportError:
    import main as rag  # type: ignore[no-redef]  # noqa: E402 — uruchomienie: cd qdrant_basic && uvicorn api:app

app = FastAPI(
    title="RAG Qdrant API",
    description="Indeksowanie plików tekstowych / PDF oraz wyszukiwanie wektorowe w Qdrancie.",
    version="0.1.0",
)


class HealthResponse(BaseModel):
    qdrant_url: str
    qdrant_ok: bool
    qdrant_error: str | None = None


class IndexResponse(BaseModel):
    ok: bool = True
    file: str
    points: int
    chunks: int


class DeleteIndexResponse(BaseModel):
    ok: bool = True
    mode: str = Field(
        ...,
        description="none — brak kolekcji; collection — usunięto całą kolekcję; filter — usunięto punkty po payload.source",
    )
    collection: str
    source: str | None = Field(None, description="Filtr payload ``source`` (tylko przy mode=filter)")
    deleted_points: int | None = Field(
        None,
        description="Liczba punktów przed usunięciem (filter); null przy usunięciu całej kolekcji",
    )


class HitItem(BaseModel):
    score: float
    text: str
    source: str
    chunk_index: int | None = None


class ComplianceAssessment(BaseModel):
    """Jedna pozycja z JSON zwracanego przez model (prompt compliance)."""

    umowa_id: int = Field(..., description="Numer chunka UMOWY z listy w prompcie (1, 2, …)")
    ryzyko: int = Field(..., ge=0, le=100)
    status: str = Field(..., description='np. "zgodna" lub "do rewizji"')
    komentarz: str
    brzmienie_oryginalne: str
    brzmienie_poprawione: str


class FullUstawaUmowaResponse(BaseModel):
    """Odpowiedź LLM: te same pola co ``answer`` / ``answer_raw`` w ``QueryResponse`` (bez ``hits``)."""

    ok: bool = True
    file: str
    ustawa_chars: int = Field(..., description="Liczba znaków treści USTAWY wysłanej do modelu")
    umowa_chars: int = Field(..., description="Liczba znaków treści UMOWY wyciągniętej z pliku i wysłanej do modelu")
    answer: list[ComplianceAssessment] | None = Field(
        None,
        description="Ten sam schemat co przy POST /query z answer=true: ComplianceAssessment[]",
    )
    answer_raw: str | None = Field(
        None,
        description="Surowy tekst modelu, gdy JSON nie przeszedł walidacji; albo gdy answer jest pustą listą [] (żeby widać było dokładną odpowiedź modelu)",
    )
    hint: str | None = Field(
        None,
        description="Opcjonalna wskazówka (np. bardzo mało tekstu z PDF — możliwy skan bez warstwy tekstu)",
    )


class QueryResponse(BaseModel):
    hits: list[HitItem]
    answer: list[ComplianceAssessment] | None = Field(
        None,
        description="Odpowiedź modelu po sparsowaniu JSON (gdy answer=true i format jest poprawny)",
    )
    answer_raw: str | None = Field(
        None,
        description="Surowy tekst modelu, gdy answer=true a JSON nie da się zwalidować; przy answer=false zawsze null",
    )


class QueryBody(BaseModel):
    query: str = Field(..., min_length=1, description="Treść zapytania")
    limit: int = Field(5, ge=1, le=50, description="Liczba fragmentów z Qdranta")
    answer: bool = Field(True, description="Wygeneruj odpowiedź z modelem czatu (wymaga CHAT_MODEL w .env)")


def _strip_llm_json_fence(text: str) -> str:
    """Usuwa otoczkę ```json ... ``` często dodawaną przez modele."""
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*\r?\n?(.*)\r?\n?```\s*$", t, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return t


def _parse_compliance_json(raw: str) -> tuple[list[ComplianceAssessment] | None, str | None]:
    """
    Zwraca (lista obiektów, None) przy sukcesie albo (None, surowy_tekst) przy błędzie parsowania / walidacji.
    """
    raw = raw.strip()
    if not raw:
        return None, ""
    try:
        data = json.loads(_strip_llm_json_fence(raw))
    except json.JSONDecodeError:
        return None, raw
    if not isinstance(data, list):
        return None, raw
    out: list[ComplianceAssessment] = []
    try:
        for item in data:
            if not isinstance(item, dict):
                return None, raw
            out.append(ComplianceAssessment.model_validate(item))
    except ValidationError:
        return None, raw
    return out, None


def _runtime_to_http(exc: RuntimeError) -> HTTPException:
    msg = str(exc)
    if msg.startswith("Brak połączenia z Qdrantem"):
        return HTTPException(status_code=503, detail=msg)
    return HTTPException(status_code=400, detail=msg)


_ALLOWED_SUFFIX = {".txt", ".md", ".pdf"}


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Sprawdza dostępność Qdranta (bez wywołań embeddingów)."""
    url = rag._qdrant_url()
    client = rag.get_qdrant()
    try:
        client.get_collections()
        return HealthResponse(qdrant_url=url, qdrant_ok=True)
    except rag.ResponseHandlingException as e:
        if rag._is_qdrant_unreachable(e):
            return HealthResponse(qdrant_url=url, qdrant_ok=False, qdrant_error=str(e))
        return HealthResponse(qdrant_url=url, qdrant_ok=False, qdrant_error=str(e))


@app.post("/index", response_model=IndexResponse, tags=["rag"])
async def index_document(
    file: UploadFile = File(..., description="Plik .txt, .md (UTF-8) lub .pdf"),
    chunk: int = Form(800, ge=64, le=50_000, description="Długość chunka w znakach"),
) -> IndexResponse:
    """Wczytuje plik, dzieli na chunki, liczy embeddingi i zapisuje punkty w Qdrancie."""
    name = file.filename or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise HTTPException(
            status_code=415,
            detail=f"Nieobsługiwany typ pliku {suffix!r}. Dozwolone: {sorted(_ALLOWED_SUFFIX)}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Pusty plik")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        tmp_path = Path(tmp.name)

    stats: dict[str, int]
    try:
        stats = rag.index_file(tmp_path, chunk, source_label=name)
    except RuntimeError as e:
        raise _runtime_to_http(e) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Błąd HTTP embeddingów: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)

    return IndexResponse(file=name, points=stats["points"], chunks=stats["chunks"])


@app.delete("/index", response_model=DeleteIndexResponse, tags=["rag"])
def delete_index(
    source: str | None = Query(
        None,
        description="Jeśli podane — usuń tylko punkty z tym ``payload.source`` (np. nazwa pliku z POST /index). "
        "Jeśli pominięte — usuń całą kolekcję Qdranta dla COLLECTION_NAME.",
    ),
) -> DeleteIndexResponse:
    """Usuwa dane z indeksu: całą kolekcję albo fragmenty jednego źródła (pole ``source`` w payload)."""
    if source is not None and not source.strip():
        raise HTTPException(status_code=400, detail="Parametr source nie może być pusty; pomiń go, aby usunąć całą kolekcję.")
    filt = source.strip() if source is not None else None
    try:
        out = rag.delete_from_index(source=filt)
    except RuntimeError as e:
        raise _runtime_to_http(e) from e
    return DeleteIndexResponse(
        mode=str(out["mode"]),
        collection=str(out["collection"]),
        source=out["source"] if out.get("source") is not None else None,
        deleted_points=out["deleted_points"],
    )


@app.post("/query", response_model=QueryResponse, tags=["rag"])
def query_rag(body: QueryBody) -> QueryResponse:
    """Wyszukiwanie semantyczne w zindeksowanej kolekcji; opcjonalnie odpowiedź LLM."""
    try:
        hits_raw = rag.search(body.query.strip(), limit=body.limit)
    except RuntimeError as e:
        raise _runtime_to_http(e) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Błąd HTTP embeddingów: {e}") from e

    hits = [
        HitItem(
            score=float(h["score"]),
            text=h.get("text") or "",
            source=h.get("source") or "",
            chunk_index=h.get("chunk_index"),
        )
        for h in hits_raw
    ]
    answer: list[ComplianceAssessment] | None = None
    answer_raw: str | None = None
    if body.answer:
        try:
            raw = rag.optional_llm_answer(body.query, hits_raw)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Błąd HTTP modelu czatu: {e}") from e
        if raw is None:
            answer_raw = None
        else:
            parsed, fallback_raw = _parse_compliance_json(raw)
            if parsed is not None:
                answer = parsed
            else:
                answer_raw = fallback_raw if fallback_raw is not None else raw
    return QueryResponse(hits=hits, answer=answer, answer_raw=answer_raw)


@app.post(
    "/compliance/full-file",
    response_model=FullUstawaUmowaResponse,
    tags=["rag"],
    summary="Pełna UMOWA z pliku vs USTAWA (LLM)",
)
async def compliance_full_file(
    ustawa: str = Form(
        ...,
        min_length=1,
        description="Treść lub fragment USTAWY (norma), według której sprawdzasz UMOWĘ",
    ),
    file: UploadFile = File(..., description="Plik z pełną treścią UMOWY (.txt, .md, .pdf)"),
) -> FullUstawaUmowaResponse:
    """
    Wczytuje **cały** plik UMOWY i wysyła go do modelu razem z tekstem USTAWY (bez Qdranta, bez chunkowania).
    Odpowiedź modelu ma **ten sam zestaw pól JSON** co przy ``POST /query`` z ``answer=true`` (``ComplianceAssessment``).
    """
    name = file.filename or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise HTTPException(
            status_code=415,
            detail=f"Nieobsługiwany typ pliku {suffix!r}. Dozwolone: {sorted(_ALLOWED_SUFFIX)}",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Pusty plik")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        tmp_path = Path(tmp.name)

    try:
        umowa_text = rag.load_document_text(tmp_path)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)

    ustawa_stripped = ustawa.strip()
    umowa_stripped = umowa_text.strip()
    if not umowa_stripped:
        raise HTTPException(
            status_code=400,
            detail="Z pliku nie uzyskano żadnego tekstu (np. PDF ze skanem bez warstwy tekstu — potrzebne OCR lub inny plik).",
        )

    ustawa_chars = len(ustawa_stripped)
    umowa_chars = len(umowa_stripped)

    try:
        raw = rag.full_ustawa_umowa_llm_answer(ustawa, umowa_text)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Błąd HTTP modelu czatu: {e}") from e

    parsed, fallback_raw = _parse_compliance_json(raw)
    hint: str | None = None
    if umowa_chars < 400 and suffix == ".pdf":
        hint = (
            "Z PDF wyciągnięto mało znaków — typowe dla skanu bez tekstu. "
            "Wgraj wersję z warstwą tekstową lub użyj OCR, inaczej model ma niewiele treści do analizy."
        )

    if parsed is not None:
        answer_raw_out: str | None = None
        if len(parsed) == 0:
            answer_raw_out = raw.strip() if raw else None
        return FullUstawaUmowaResponse(
            file=name,
            ustawa_chars=ustawa_chars,
            umowa_chars=umowa_chars,
            answer=parsed,
            answer_raw=answer_raw_out,
            hint=hint,
        )
    return FullUstawaUmowaResponse(
        file=name,
        ustawa_chars=ustawa_chars,
        umowa_chars=umowa_chars,
        answer=None,
        answer_raw=fallback_raw if fallback_raw is not None else raw,
        hint=hint,
    )
