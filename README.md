# Regulatory Change Monitor

Application for monitoring changes in legal acts and verifying contract compliance with current regulations.

## Architecture

```
frontend/        React + Vite (port 5173)
app/             FastAPI — main API (port 8000)
qdrant_basic/    RAG API + Qdrant (ports 8080 / 6333)
docker/mongodb/  MongoDB (port 27017)
```

## Requirements

- Docker + Docker Compose
- Node.js 20+
- Python 3.12+

## Setup

### 1. Docker Network

All containers communicate over a shared network. Create it once:

```bash
docker network create hackaton_net
```

### 2. MongoDB

```bash
cd docker/mongodb
docker compose up -d
```

### 3. RAG (Qdrant + RAG API)

Copy the environment file and fill in your keys:

```bash
cd qdrant_basic
cp .env.example .env   # or edit .env directly
```

Required variables in `qdrant_basic/.env`:

```
QDRANT_URL=http://localhost:6333
COLLECTION_NAME=qdrant_basic
OPENAI_API_KEY=<key>
OPENAI_BASE_URL=<Azure OpenAI endpoint>
EMBEDDING_MODEL=text-embedding-3-small
CHAT_MODEL=gpt-4o-mini
CHUNK_CHARS=800
```

Start:

```bash
docker compose up -d
```

RAG API Swagger: http://localhost:8080/docs

### 4. Main API (FastAPI)

```bash
cd docker/api
docker compose up -d
```

Main API Swagger: http://localhost:8000/docs

Environment variables (optional, defaults set in docker-compose.yml):

| Variable | Default | Description |
|---|---|---|
| `ANCHOR_BACKEND` | `stub` | Blockchain backend (`stub` / `solana` / `ethereum`) |
| `RAG_SERVICE_URL` | `http://qdrant_basic-rag-api-1:8080` | RAG container address |
| `MONGODB_URI` | `mongodb://mongodb:27017/` | MongoDB connection string |

### 5. Frontend

```bash
cd frontend
npm install
npm run dev
```

App available at: http://localhost:5173

Vite proxy forwards `/api/*` → `http://localhost:8000`.

## Startup Order

```bash
docker network create hackaton_net
cd docker/mongodb && docker compose up -d
cd qdrant_basic   && docker compose up -d
cd docker/api     && docker compose up -d
cd frontend       && npm install && npm run dev
```

## ISAP Crawler

Scripts for fetching and processing legal acts from ISAP:

```bash
# Fetch list of acts
python isap_crawler.py

# Extract changes from acts
python isap_extract_changes.py
```

Data is stored in MongoDB (collection `legal_acts`).
