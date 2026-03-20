# 🚀 Crawl Index Server

> Local-first semantic search server — crawl websites, index content, and search with AI

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

---

## ✨ What It Does

Turns any website's documentation into your **own local AI knowledge base**.

```
🌐 Website  ──▶  📦 Cloudflare Crawl  ──▶  💾 SQLite  ──▶  🧠 Embeddings  ──▶  🔍 Semantic Search
```

### Features

| Feature | Description |
|----------|-------------|
| 🔄 **Auto Crawl** | Cloudflare's browser rendering fetches pages |
| 💾 **Local Storage** | Stores markdown in SQLite |
| 🧠 **Embedding** | Vectorizes with sentence-transformers |
| 🔍 **Semantic Search** | Fast vector search with Qdrant |
| 🤖 **MCP Server** | Stdio-based tools for AI agents |
| 🎨 **Admin UI** | Visual management panel in browser |

---

## 🛠️ Setup

```bash
# 1. Install dependencies
uv sync

# 2. Create environment file
cp .env.example .env

# 3. Start server
uv run crawl-index-server
```

> 💡 **Tip:** Server automatically opens browser when started!

**URL:** [http://127.0.0.1:8000/admin/sources](http://127.0.0.1:8000/admin/sources)

---

## ⚙️ Environment Variables

```env
# Cloudflare Browser Rendering (required for crawl)
CF_ACCOUNT_ID=your_account_id
CF_API_TOKEN=your_api_token

# Optional (defaults shown)
APP_HOST=127.0.0.1
APP_PORT=8000
QDRANT_URL=http://127.0.0.1:6333
EMBEDDING_MODEL=intfloat/multilingual-e5-small
```

> ⚠️ Without Cloudflare credentials, crawl is disabled but search and admin UI still work.

---

## 🤖 MCP Server

Full-featured MCP server for AI agents!

### Installation

```json
{
  "mcpServers": {
    "crawl-index": {
      "command": "uv",
      "args": ["--directory", "/path/to/crawl-index-server", "run", "python", "-m", "app.mcp_server"]
    }
  }
}
```

### Available Tools

| Tool | Description |
|------|-------------|
| `search_docs` | 📚 Semantic search in indexed documents |
| `list_sources` | 📋 List all crawl sources |
| `create_source` | ➕ Add new source |
| `trigger_crawl` | ▶️ Start crawl |
| `reindex_source` | 🔄 Re-index a source |
| `list_jobs` | 📊 View crawl jobs |
| `get_job` | 🔎 Get job details |
| `retry_job` | 🔁 Retry failed job |
| `health_check` | 💚 Check system health |

### Example Usage

```python
# AI agent searching documentation
result = search_docs(query="How does Next.js App Router work?", limit=5)

# Add new site
result = create_source(
    name="React Docs",
    start_url="https://react.dev/docs",
    allowed_domains=["react.dev"],
    crawl_depth=2
)

# Update content
result = reindex_source(source_id="abc-123")
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     crawl-index-server                   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   ┌─────────────┐    ┌─────────────┐    ┌───────────┐  │
│   │   FastAPI  │    │  Scheduler  │    │  MCP      │  │
│   │   REST API │    │  (APScheduler)│   │  Server   │  │
│   └──────┬──────┘    └──────┬──────┘    └─────┬─────┘  │
│          │                   │                   │        │
│   ┌──────┴───────────────────┴───────────────────┴────┐ │
│   │              Service Container                       │ │
│   │  ┌────────────┐  ┌───────────┐  ┌─────────────┐   │ │
│   │  │  Source   │  │   Crawl   │  │   Search    │   │ │
│   │  │  Service  │  │ Coordinator│  │   Service   │   │ │
│   │  └────────────┘  └───────────┘  └─────────────┘   │ │
│   └──────────────────────┬───────────────────────────┘ │
│                          │                               │
│   ┌──────────────────────┴───────────────────────────┐ │
│   │                  Vector Store                     │ │
│   │   ┌─────────────┐          ┌─────────────────┐   │ │
│   │   │  Embedding │          │  Qdrant Client  │   │ │
│   │   │  Service   │          │  (HTTP/REST)   │   │ │
│   │   └─────────────┘          └────────┬────────┘   │ │
│   └─────────────────────────────────────┼────────────┘ │
│                                          │             │
└──────────────────────────────────────────┼─────────────┘
                                           │
                              ┌─────────────┴─────────────┐
                              │      Qdrant Server       │
                              │    (Vector Storage)      │
                              └──────────────────────────┘
```

---

## 📦 Tech Stack

| Layer | Technology |
|-------|------------|
| 🌐 API | FastAPI + Uvicorn |
| 📊 Database | SQLite + SQLModel |
| 🧠 Embeddings | sentence-transformers |
| 🔍 Vector Store | Qdrant |
| 📝 UI | Jinja2 Templates |
| 🤖 AI Integration | MCP (Model Context Protocol) |
| ⏰ Jobs | APScheduler |

---

## 🧪 Development

```bash
# Run tests
uv run pytest

# Format code
uv run ruff format .

# Lint
uv run ruff check .
```

---

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.
