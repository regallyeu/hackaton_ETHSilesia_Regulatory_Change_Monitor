#!/usr/bin/env python3
"""
Minimal Qdrant demo: Docker Qdrant, fixed-size character chunking, dense vectors,
index text or PDF files, vector search + optional LLM answer (OpenAI-compatible HTTP only).

Dependencies: qdrant-client, httpx, python-dotenv, pypdf (see requirements.txt).

Usage:
  docker compose up -d
  pip install -r requirements.txt
  cp .env.example .env   # set OPENAI_API_KEY
  python main.py index --file sample.txt --chunk 500
  python main.py index --file dokument.pdf --chunk 800
  python main.py query "Co jest w dokumencie?"
  uvicorn api:app --reload --port 8080   # Swagger: http://localhost:8080/docs
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import sys
import uuid
from pathlib import Path
from textwrap import dedent
from typing import Iterable
from urllib.parse import urlencode, urlparse

import httpx
from dotenv import load_dotenv
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException
from qdrant_client.http.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

load_dotenv(Path(__file__).resolve().parent / ".env")


def _qdrant_url() -> str:
    return os.environ.get("QDRANT_URL", "http://localhost:6333").rstrip("/")


def _is_qdrant_unreachable(exc: BaseException) -> bool:
    """True if this error is a TCP / HTTP connection failure to Qdrant."""
    if isinstance(exc, ResponseHandlingException):
        src = getattr(exc, "source", None)
        if src is not None and _is_qdrant_unreachable(src):
            return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (errno.ECONNREFUSED, errno.EHOSTUNREACH):
        return True
    cause = exc.__cause__
    if cause is not None and _is_qdrant_unreachable(cause):
        return True
    return False


def _raise_qdrant_unreachable(exc: BaseException) -> None:
    if not _is_qdrant_unreachable(exc):
        raise exc
    url = _qdrant_url()
    raise RuntimeError(
        f"Brak połączenia z Qdrantem ({url})."
        f"Uruchom Qdranta lokalnie: cd qdrant_basic && docker compose up -d\n"
    ) from exc


def load_document_text(path: Path) -> str:
    """Load plain text from UTF-8 files or extract text from PDF (digital text layers)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise RuntimeError(f"PDF is password-protected or encrypted: {path}")
        parts: list[str] = []
        for page in reader.pages:
            t = page.extract_text()
            if t and t.strip():
                parts.append(t.strip())
        return "\n\n".join(parts)
    return path.read_text(encoding="utf-8")


def chunk_by_chars(text: str, n: int) -> list[str]:
    """Non-overlapping chunks of up to n characters (last chunk may be shorter)."""
    if n <= 0:
        raise ValueError("chunk size must be positive")
    text = text.replace("\r\n", "\n")
    return [text[i : i + n] for i in range(0, len(text), n)] if text else []


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in .env (needed for embeddings and optional chat).")
    return key


def _openai_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


def _azure_headers() -> dict[str, str]:
    return {"api-key": _api_key(), "Content-Type": "application/json"}


def _base_url() -> str:
    return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _azure_openai_config() -> tuple[str, str] | None:
    """
    If using Azure OpenAI, return (resource_endpoint, api_version), else None.
    Triggered by OPENAI_API_TYPE=azure or OPENAI_BASE_URL host *.openai.azure.com / *.cognitiveservices.azure.com.
    """
    explicit = os.environ.get("OPENAI_API_TYPE", "").strip().lower() == "azure"
    raw = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw.rstrip("/"))
    host = (parsed.hostname or "").lower()
    azure_host = host.endswith(".openai.azure.com") or host.endswith(".cognitiveservices.azure.com")
    if not explicit and not azure_host:
        return None
    endpoint = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    version = os.environ.get("AZURE_OPENAI_API_VERSION", "2023-05-15").strip()
    return endpoint, version


def _embeddings_url_and_body(model: str, texts: list[str]) -> tuple[str, dict, dict[str, str]]:
    """(url, json_body, headers) for OpenAI or Azure OpenAI."""
    az = _azure_openai_config()
    if az:
        endpoint, api_version = az
        deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip() or model
        q = urlencode({"api-version": api_version})
        url = f"{endpoint}/openai/deployments/{deployment}/embeddings?{q}"
        return url, {"input": texts}, _azure_headers()
    url = f"{_base_url()}/embeddings"
    return url, {"model": model, "input": texts}, _openai_headers()


def _chat_completions_url_and_body(model: str, messages: list[dict], temperature: float) -> tuple[str, dict, dict[str, str]]:
    az = _azure_openai_config()
    if az:
        endpoint, api_version = az
        q = urlencode({"api-version": api_version})
        url = f"{endpoint}/openai/deployments/{model}/chat/completions?{q}"
        return url, {"messages": messages, "temperature": temperature}, _azure_headers()
    url = f"{_base_url()}/chat/completions"
    return url, {"model": model, "messages": messages, "temperature": temperature}, _openai_headers()


def embed_texts(texts: list[str], model: str | None = None) -> tuple[list[list[float]], int]:
    """Returns (vectors, dimension) using OpenAI-compatible /embeddings."""
    if not texts:
        return [], 0
    model = model or os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    url, body, headers = _embeddings_url_and_body(model, texts)
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    items = sorted(data["data"], key=lambda x: x["index"])
    vectors = [it["embedding"] for it in items]
    dim = len(vectors[0])
    return vectors, dim


def get_qdrant() -> QdrantClient:
    # Serwer w docker-compose (np. v1.12) może być „za stary” vs klient pip — ostrzeżenie szumu; połączenie działa.
    return QdrantClient(url=_qdrant_url(), check_compatibility=False)


def _qdrant_require_reachable(client: QdrantClient) -> None:
    """Fail fast before expensive embedding calls if Qdrant is down."""
    try:
        client.get_collections()
    except ResponseHandlingException as e:
        _raise_qdrant_unreachable(e)


def collection_name() -> str:
    return os.environ.get("COLLECTION_NAME", "qdrant_basic")


def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    name = collection_name()
    try:
        if client.collection_exists(name):
            info = client.get_collection(name)
            params = info.config.params.vectors
            if params is None:
                raise RuntimeError("Collection has no vector config")
            # Single unnamed vector
            existing = getattr(params, "size", None)
            if existing is not None and int(existing) != vector_size:
                raise RuntimeError(
                    f"Collection {name!r} has vector size {existing}, need {vector_size}. "
                    f"Delete the collection in Qdrant or pick another COLLECTION_NAME."
                )
            return
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
    except ResponseHandlingException as e:
        _raise_qdrant_unreachable(e)


def index_file(path: Path, chunk_chars: int, *, source_label: str | None = None) -> dict[str, int]:
    """Index file into Qdrant. ``source_label`` overrides payload ``source`` (e.g. original upload name)."""
    text = load_document_text(path)
    chunks = chunk_by_chars(text, chunk_chars)
    if not chunks:
        return {"points": 0, "chunks": 0}

    client = get_qdrant()
    _qdrant_require_reachable(client)
    # Embed in batches to stay within API limits
    batch_size = 64
    all_vectors: list[list[float]] = []
    dim = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        vecs, dim = embed_texts(batch)
        all_vectors.extend(vecs)

    ensure_collection(client, dim)
    name = collection_name()
    points: list[PointStruct] = []
    for idx, (vec, chunk) in enumerate(zip(all_vectors, chunks)):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={
                    "text": chunk,
                    "source": source_label or str(path.resolve()),
                    "chunk_index": idx,
                },
            )
        )
    try:
        client.upsert(collection_name=name, points=points)
    except ResponseHandlingException as e:
        _raise_qdrant_unreachable(e)
    return {"points": len(points), "chunks": len(chunks)}


def search(query: str, limit: int = 5) -> list[dict]:
    client = get_qdrant()
    name = collection_name()
    try:
        if not client.collection_exists(name):
            raise RuntimeError(f"Collection {name!r} does not exist. Run index first.")
        qvec, _dim = embed_texts([query])
        hits = client.query_points(
            collection_name=name,
            query=qvec[0],
            limit=limit,
            with_payload=True,
        )
    except ResponseHandlingException as e:
        _raise_qdrant_unreachable(e)
    out: list[dict] = []
    for p in hits.points:
        out.append(
            {
                "score": p.score,
                "text": (p.payload or {}).get("text", ""),
                "source": (p.payload or {}).get("source", ""),
                "chunk_index": (p.payload or {}).get("chunk_index"),
            }
        )
    return out


def delete_from_index(*, source: str | None = None) -> dict[str, str | int | None]:
    """
    Usuwa dane z Qdranta. ``source=None`` — usuwa całą kolekcję (jeśli istnieje).
    ``source`` ustawione — usuwa wyłącznie punkty z ``payload.source`` równym temu łańcuchowi.
    """
    client = get_qdrant()
    _qdrant_require_reachable(client)
    name = collection_name()
    if not client.collection_exists(name):
        return {"mode": "none", "collection": name, "deleted_points": 0, "source": None}

    if source is None:
        try:
            client.delete_collection(collection_name=name)
        except ResponseHandlingException as e:
            _raise_qdrant_unreachable(e)
        return {"mode": "collection", "collection": name, "deleted_points": None, "source": None}

    flt = Filter(must=[FieldCondition(key="source", match=MatchValue(value=source))])
    try:
        n = int(client.count(collection_name=name, count_filter=flt, exact=True).count)
        client.delete(collection_name=name, points_selector=flt)
    except ResponseHandlingException as e:
        _raise_qdrant_unreachable(e)
    return {"mode": "filter", "collection": name, "deleted_points": n, "source": source}


def optional_llm_answer(query: str, passages: list[dict]) -> str | None:
    """If CHAT_MODEL is set, call chat completions with retrieved context."""
    model = os.environ.get("CHAT_MODEL", "gpt-4o-mini").strip()
    if not model:
        return None
    umowa_lines: list[str] = []
    for i, p in enumerate(passages, start=1):
        src = (p.get("source") or "").strip() or "(brak źródła)"
        meta_parts = [f"Źródło: {src}"]
        if p.get("chunk_index") is not None:
            meta_parts.append(f"chunk_index w dokumencie: {p.get('chunk_index')}")
        head = f"{i}. " + ", ".join(meta_parts)
        body = (p.get("text") or "").strip()
        umowa_lines.append(f"{head}\n{body}")
    umowa_list = (
        "\n\n ============== \n\n".join(umowa_lines)
        if umowa_lines
        else "(brak chunków UMOWY — zwróć pustą tablicę JSON [])"
    )
    system = dedent(
        """
        Jesteś prawnikiem specjalizującym się w compliance i analizie zgodności dokumentów.
        Odpowiadasz wyłącznie po polsku.
        Bazujesz wyłącznie na dostarczonym kontekście – nie używaj wiedzy zewnętrznej.
        Odpowiadasz zwięźle, precyzyjnie i w sposób ustrukturyzowany.
        """
    ).strip()
    prompt_intro = dedent(
        """
        Otrzymujesz dane w dwóch sekcjach (jak w poniższej numeracji):

        1. Fragment ustawy (USTAWA) — treść pod nagłówkiem „USTAWA”.
        2. Fragmenty umowy (UMOWA) — ponumerowana lista chunków (1., 2., 3., …) pod nagłówkiem „UMOWA”.
           Pole `umowa_id` w wynikowym JSON musi być **tym samym numerem** co numer chunka na liście.
        """
    ).strip()
    prompt_outro = dedent(
        """
        Twoim zadaniem jest:

        Dla KAŻDEGO fragmentu UMOWY:
        - porównać go z USTAWA
        - ocenić zgodność
        - oszacować ryzyko niezgodności
        - zaproponować poprawne brzmienie fragmentu UMOWY, które jest zgodne z USTAWA, jeśli oszacowane ryzyko jest wyższe niż 50

        Zasady oceny:
        - 0 = pełna zgodność
        - 1–30 = niskie ryzyko (drobne różnice, brak istotnych naruszeń)
        - 31–70 = średnie ryzyko (potencjalna niezgodność lub niejasność)
        - 71–100 = wysokie ryzyko (wyraźna sprzeczność lub brak wymaganych elementów)

        Wynik zwróć WYŁĄCZNIE jako poprawny JSON (bez komentarzy poza JSON).

        Format:
        [
        {
            "umowa_id": <int>,
            "ryzyko": <int 0-100>,
            "status": "zgodna" | "do rewizji",
            "komentarz": "<krótkie uzasadnienie decyzji, max 2 zdania>",
            "brzmienie_oryginalne": "<brzmienie fragmentu UMOWY>",
            "brzmienie_poprawione": "<poprawne brzmienie fragmentu UMOWY>"
        }
        ]

        Dodatkowe zasady:
        - oceń KAŻDY chunk UMOWY osobno
        - nie pomijaj żadnego chunku
        - nie dodawaj żadnych pól poza wskazanymi
        - jeśli brak powiązania z USTAWA → ustaw ryzyko = 0, komentarz: "brak bezpośredniego powiązania" i poprawne_brzmienie: ""
        """
    ).strip()
    prompt = "\n\n".join(
        [
            prompt_intro,
            "--- USTAWA ---",
            query.strip(),
            "--- UMOWA (chunki) ---",
            umowa_list,
            prompt_outro,
        ]
    )

    print(prompt)
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": prompt,
        },
    ]
    url, body, headers = _chat_completions_url_and_body(model, messages, 0.2)
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()

    print(data["choices"][0]["message"]["content"].strip())
    return data["choices"][0]["message"]["content"].strip()


def full_ustawa_umowa_llm_answer(ustawa: str, umowa: str) -> str:
    """
    Pełny tekst USTAWY i pełny tekst UMOWY w jednym wywołaniu modelu (bez Qdranta, bez chunkowania).
    Oczekiwany JSON: ten sam zestaw pól co w odpowiedzi ``optional_llm_answer`` (umowa_id, ryzyko, status, …).
    """
    model = os.environ.get("CHAT_MODEL", "gpt-4o-mini").strip()
    if not model:
        raise RuntimeError("Ustaw CHAT_MODEL w .env, aby użyć weryfikacji LLM.")
    ustawa_t = ustawa.strip()
    umowa_t = umowa.strip()
    if not ustawa_t:
        raise RuntimeError("Treść USTAWY nie może być pusta.")
    if not umowa_t:
        raise RuntimeError("Treść UMOWY nie może być pusta.")

    system = dedent(
        """
        Jesteś prawnikiem specjalizującym się w compliance i analizie zgodności dokumentów.
        Odpowiadasz wyłącznie po polsku.
        Bazujesz wyłącznie na dostarczonym kontekście – nie używaj wiedzy zewnętrznej.
        Odpowiadasz zwięźle, precyzyjnie i w sposób ustrukturyzowany.
        """
    ).strip()
    prompt_intro = dedent(
        """
        Otrzymujesz dwie sekcje:

        1. USTAWA — treść pod nagłówkiem „USTAWA”.
        2. UMOWA — **pełny** tekst umowy pod nagłówkiem „UMOWA (pełna treść)”.

        Odpowiedź musi być tablicą JSON z obiektami o **dokładnie** tych samych polach i znaczeniu co przy analizie chunków:
        umowa_id, ryzyko, status, komentarz, brzmienie_oryginalne, brzmienie_poprawione (wartości status: „zgodna” | „do rewizji”).
        """
    ).strip()
    prompt_outro = dedent(
        """
        Twoim zadaniem jest:

        Dla KAŻDEGO fragmentu UMOWY:
        - porównać go z USTAWA
        - ocenić zgodność
        - oszacować ryzyko niezgodności
        - zaproponować poprawne brzmienie fragmentu UMOWY, które jest zgodne z USTAWA, jeśli oszacowane ryzyko jest wyższe niż 50

        Zasady oceny:
        - 0 = pełna zgodność
        - 1–30 = niskie ryzyko (drobne różnice, brak istotnych naruszeń)
        - 31–70 = średnie ryzyko (potencjalna niezgodność lub niejasność)
        - 71–100 = wysokie ryzyko (wyraźna sprzeczność lub brak wymaganych elementów)

        Wynik zwróć WYŁĄCZNIE jako poprawny JSON (bez komentarzy poza JSON).

        Format:
        [
        {
            "umowa_id": <int>,
            "ryzyko": <int 0-100>,
            "status": "zgodna" | "do rewizji",
            "komentarz": "<krótkie uzasadnienie decyzji, max 2 zdania>",
            "brzmienie_oryginalne": "<brzmienie fragmentu UMOWY>",
            "brzmienie_poprawione": "<poprawne brzmienie fragmentu UMOWY>"
        }
        ]

        Dodatkowe zasady (pełny tekst UMOWY, bez listy chunków):
        - pracuj na całym tekście UMOWY powyżej
        - zwróć po jednym obiekcie JSON na każdy fragment UMOWY istotny w świetle USTAWY; pole ``umowa_id`` — kolejne liczby całkowite od 1
        - w ``brzmienie_oryginalne`` umieść cytat lub wierny skrót fragmentu UMOWY
        - nie dodawaj żadnych pól poza wskazanymi
        - jeśli brak powiązania fragmentu z USTAWĄ → ustaw ryzyko = 0, komentarz: "brak bezpośredniego powiązania" i brzmienie_poprawione: ""
        - jeśli tekst UMOWY powyżej jest **niepusty**, nie zwracaj samej pustej tablicy [] — zwróć co najmniej jeden obiekt
          (np. umowa_id=1 z ogólną oceną całości umowy względem USTAWY i cytatem lub skrótem z początku UMOWY w brzmienie_oryginalne).
        - zwróć [] wyłącznie gdy UMOWA jest faktycznie pusta lub nie zawiera żadnego sensownego zapisu do oceny.
        """
    ).strip()
    prompt = "\n\n".join(
        [
            prompt_intro,
            "--- USTAWA ---",
            ustawa_t,
            "--- UMOWA (pełna treść) ---",
            umowa_t,
            prompt_outro,
        ]
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    url, body, headers = _chat_completions_url_and_body(model, messages, 0.2)
    with httpx.Client(timeout=180.0) as client:
        r = client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    msg = data["choices"][0].get("message") or {}
    raw = (msg.get("content") or "").strip()
    if not raw:
        raise RuntimeError("Model zwrócił pustą treść odpowiedzi (brak content).")
    return raw


def cmd_index(args: argparse.Namespace) -> int:
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    chunk_n = int(args.chunk or os.environ.get("CHUNK_CHARS", "800"))
    stats = index_file(path, chunk_n)
    print(json.dumps({"ok": True, "file": str(path), **stats}, ensure_ascii=False, indent=2))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    hits = search(args.query.strip(), limit=args.limit)
    print("--- retrieved chunks ---")
    for h in hits:
        print(f"score={h['score']:.4f} chunk={h.get('chunk_index')} source={h.get('source')}")
        preview = (h.get("text") or "")[:500]
        print(preview + ("…" if len(h.get("text") or "") > 500 else ""))
        print()
    if args.answer:
        ans = optional_llm_answer(args.query, hits)
        if ans:
            print("--- model answer ---")
            print(ans)
        else:
            print("(Set CHAT_MODEL in .env for generated answers.)", file=sys.stderr)
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Minimal Qdrant index + query")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index a UTF-8 text file or PDF")
    p_index.add_argument(
        "--file",
        required=True,
        help="Path to .txt / .md (UTF-8) or .pdf (text layer; scanned PDFs need OCR elsewhere)",
    )
    p_index.add_argument("--chunk", type=int, default=None, help="Characters per chunk (default: CHUNK_CHARS env)")
    p_index.set_defaults(func=cmd_index)

    p_query = sub.add_parser("query", help="Vector search (+ optional LLM answer)")
    p_query.add_argument("query", help="Search question")
    p_query.add_argument("--limit", type=int, default=5)
    p_query.add_argument("--answer", action="store_true", help="Call chat model with top passages")
    p_query.set_defaults(func=cmd_query)

    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
