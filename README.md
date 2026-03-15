# Crawl Index Server

Cloudflare `/crawl` endpoint'i ile icerik toplayip yerelde indeksleyen, semantic search icin embedding ureten local-first mini sunucu.

## What It Does

- Starts Cloudflare crawl jobs for documentation-heavy sites
- Polls crawl job progress until completion
- Stores fetched markdown locally in SQLite
- Chunks and embeds changed documents only
- Indexes vectors in local Qdrant storage
- Exposes REST endpoints and a small admin UI for sources, jobs, documents, and search

## Stack

- FastAPI
- SQLite
- Qdrant local mode
- APScheduler
- sentence-transformers

## Setup

```bash
uv sync
cp .env.example .env
uv run python -m scripts.bootstrap
uv run crawl-index-server
```

Open [http://127.0.0.1:8000/admin/sources](http://127.0.0.1:8000/admin/sources)

When started through `crawl-index-server`, the local admin UI waits until the HTTP server is reachable and then opens automatically in your browser.

## Required Environment Variables

- `CF_ACCOUNT_ID`
- `CF_API_TOKEN`

Without Cloudflare credentials the UI and search still work, but crawl submission stays disabled.

## MCP Setup

The repository also exposes a local `stdio` MCP server that uses the same SQLite and Qdrant data.

Run it directly:

```bash
uv run python -m app.mcp_server
```

Or use the packaged script:

```bash
uv run crawl-index-mcp
```

The MCP process does not start the Web UI and does not open a browser tab. It only exposes MCP tools over stdio.

Example MCP config:

```json
{
  "mcpServers": {
    "crawl-index": {
      "command": "uv",
      "args": [
        "--directory",
        "/ABSOLUTE/PATH/TO/crawl-index-server",
        "run",
        "python",
        "-m",
        "app.mcp_server"
      ]
    }
  }
}
```
