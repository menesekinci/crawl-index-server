# 🚀 Crawl Index Server

> Local-first semantic search sunucusu — web sitelerinden içerik topla, indeksle, ara

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

---

## ✨ Ne İşe Yarar?

Bir web sitesinin dokümantasyonunu çekip **kendi local AI bilgi tabanına** dönüştürür.

```
🌐 Web Sitesi  ──▶  📦 Cloudflare Crawl  ──▶  💾 SQLite  ──▶  🧠 Embeddings  ──▶  🔍 Semantic Search
```

### Özellikleri

| Özellik | Açıklama |
|----------|----------|
| 🔄 **Otomatik Crawl** | Cloudflare'ın browser rendering ile sayfaları çeker |
| 💾 **Local Storage** | SQLite'da markdown olarak saklar |
| 🧠 **Embedding** | Sentence-transformers ile vektörleştirir |
| 🔍 **Semantic Search** | Qdrant ile hızlı vektör araması |
| 🤖 **MCP Server** | AI ajanları için stdio tabanlı tool'lar |
| 🎨 **Admin UI** | Tarayıcıda görsel yönetim paneli |

---

## 🛠️ Kurulum

```bash
# 1. Dependencies yükle
uv sync

# 2. Environment dosyası oluştur
cp .env.example .env

# 3. Başlat
uv run crawl-index-server
```

> 💡 **İpucu:** Server başladığında tarayıcı otomatik açılır!

**Adres:** [http://127.0.0.1:8000/admin/sources](http://127.0.0.1:8000/admin/sources)

---

## ⚙️ Environment Değişkenleri

```env
# Cloudflare Browser Rendering (crawl için gerekli)
CF_ACCOUNT_ID=your_account_id
CF_API_TOKEN=your_api_token

# Opsiyonel (defaults gösteriliyor)
APP_HOST=127.0.0.1
APP_PORT=8000
QDRANT_URL=http://127.0.0.1:6333
EMBEDDING_MODEL=intfloat/multilingual-e5-small
```

> ⚠️ Cloudflare olmadan crawl çalışmaz ama arama ve yönetim paneline erişebilirsin.

---

## 🤖 MCP Server

AI ajanları için tam teşekküllü MCP server!

### Kurulum

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

### Kullanılabilir Tool'lar

| Tool | Açıklama |
|------|----------|
| `search_docs` | 📚 Indexed dokümanlarda semantic arama |
| `list_sources` | 📋 Tüm crawl kaynaklarını listele |
| `create_source` | ➕ Yeni kaynak ekle |
| `trigger_crawl` | ▶️ Crawl başlat |
| `reindex_source` | 🔄 Kaynağı yeniden indeksle |
| `list_jobs` | 📊 Crawl işlerini görüntüle |
| `get_job` | 🔎 İş detaylarını al |
| `retry_job` | 🔁 Başarısız işi yeniden dene |
| `health_check` | 💚 Sistem sağlığını kontrol et |

### Örnek Kullanım

```python
# AI ajanı dokümantasyonda arıyor
result = search_docs(query="Next.js App Router nasıl çalışır?", limit=5)

# Yeni bir site ekle
result = create_source(
    name="React Docs",
    start_url="https://react.dev/docs",
    allowed_domains=["react.dev"],
    crawl_depth=2
)

# İçerik güncelleme
result = reindex_source(source_id="abc-123")
```

---

## 🏗️ Mimari

```
┌─────────────────────────────────────────────────────────┐
│                     crawl-index-server                   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│   ┌─────────────┐    ┌─────────────┐    ┌───────────┐ │
│   │   FastAPI   │    │  Scheduler  │    │  MCP      │ │
│   │   REST API  │    │  (APScheduler)│    │  Server   │ │
│   └──────┬──────┘    └──────┬──────┘    └─────┬─────┘ │
│          │                   │                   │       │
│   ┌──────┴───────────────────┴───────────────────┴─────┐ │
│   │              Service Container                      │ │
│   │  ┌────────────┐  ┌───────────┐  ┌─────────────┐  │ │
│   │  │  Source    │  │   Crawl   │  │   Search    │  │ │
│   │  │  Service   │  │ Coordinator│  │   Service   │  │ │
│   │  └────────────┘  └───────────┘  └─────────────┘  │ │
│   └──────────────────────┬────────────────────────────┘ │
│                          │                              │
│   ┌──────────────────────┴────────────────────────────┐ │
│   │                  Vector Store                      │ │
│   │   ┌─────────────┐          ┌─────────────────┐   │ │
│   │   │  Embedding  │          │  Qdrant Client  │   │ │
│   │   │  Service   │          │  (HTTP/REST)    │   │ │
│   │   └─────────────┘          └────────┬────────┘   │ │
│   └─────────────────────────────────────┼────────────┘ │
│                                          │              │
└──────────────────────────────────────────┼──────────────┘
                                           │
                              ┌─────────────┴────────────┐
                              │      Qdrant Server       │
                              │    (Vector Storage)      │
                              └──────────────────────────┘
```

---

## 📦 Teknoloji Stack

| Katman | Teknoloji |
|--------|-----------|
| 🌐 API | FastAPI + Uvicorn |
| 📊 Database | SQLite + SQLModel |
| 🧠 Embeddings | sentence-transformers |
| 🔍 Vector Store | Qdrant |
| 📝 UI | Jinja2 Templates |
| 🤖 AI Integration | MCP (Model Context Protocol) |
| ⏰ Jobs | APScheduler |

---

## 🧪 Geliştirme

```bash
# Test çalıştır
uv run pytest

# Kod formatle
uv run ruff format .

# Lint kontrol
uv run ruff check .
```

---

## 📝 Lisans

MIT License - detaylar için [LICENSE](LICENSE) dosyasına bak.
