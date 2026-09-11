# Searchium

Desktop search engine for your files with AI-powered search, chat, and full-text indexing. **All premium features included for free.**

## Features

### Search
- **Fuzzy Search** — typo-resistant, finds "python" when you type "pyton"
- **Semantic Search** — find files by meaning, not just keywords (vector embeddings)
- **Full-text Indexing** — index millions of files with Typesense
- **Find Similar Files** — find documents related to any file via semantic similarity

### AI-Powered
- **Chat with Files** — ask questions about your indexed documents (RAG pipeline)
- **MCP/Agentic Support** — 8 tools for AI agents (Claude, GPT, etc.)

### Infrastructure
- **File Monitoring** — real-time file change detection
- **Multi-format Support** — PDF, DOCX, images, code, and 100+ formats via Apache Tika
- **Remote Access** — accessible from any device on your network
- **Russian/English UI** — auto-detects browser language
- **17x Faster Indexing** — batch upserts, 8 parallel workers

## Installation

### Requirements
- Python 3.10+
- 4GB+ RAM recommended

### Install from GitHub
```bash
git clone https://github.com/zDEBRYrp/searchium.git
cd searchium
pip install .
searchium
```

### Install in development mode
```bash
git clone https://github.com/zDEBRYrp/searchium.git
cd searchium
pip install -e .
searchium
```

Browser opens at `http://localhost:8274` (or your LAN IP for remote access)

### Windows-specific notes
- Ensure Python 3.10+ is installed and on PATH
- If you see `UnicodeEncodeError`, run `chcp 65001` before starting

## Configuration

### Environment Variables
Create `.env` file in your app data directory:
- Windows: `%LOCALAPPDATA%/searchium/.env`
- Linux/Mac: `~/.config/searchium/.env` or `./.env`

```env
# GPU mode (optional)
FILEBRAIN_GPU_MODE=force-cpu

# Typesense API key
FILEBRAIN_TYPESENSE_API_KEY=xyz...

# Chat with Files (optional)
OPENAI_API_KEY=sk-...
CHAT_MODEL=gpt-4o-mini

# Or use Anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

## API

REST API at `http://localhost:8274/api/v1/`

### Search
```bash
# Fuzzy text search
curl -X POST http://localhost:8274/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "pyton", "per_page": 10}'

# Semantic search (by meaning)
curl -X POST http://localhost:8274/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "machine learning", "semantic": true}'

# Find similar files
curl -X POST http://localhost:8274/api/v1/chat/similar \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/file.pdf"}'
```

### Chat (requires LLM API key)
```bash
curl -X POST http://localhost:8274/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What documents do I have about Python?"}'
```

### MCP Server
```bash
# For Claude Desktop / AI agents
python -m searchium.mcp_server --stdio
```

### Other Endpoints
- `GET /api/v1/crawler/status` — indexing status
- `POST /api/v1/crawler/start` — start indexing
- `GET /api/v1/stats/recent-files` — recently indexed files
- `GET /api/v1/i18n/ru` — Russian translations
- `GET /api/v1/i18n/available` — available languages

## What's Changed (vs File Brain 0.1.28)

### Performance
- **Batch upserts** — Typesense `import_()` API (200 docs/call instead of 1)
- **8 parallel indexing workers** via `ThreadPoolExecutor`
- **Fast change detection** — mtime+size instead of MD5 per file
- **Skipped redundant Tika MIME detection** — uses local `mimetypes`

### New Features
- **Fuzzy search** — `num_typos=2`, prefix matching
- **Semantic search** — vector query via `paraphrase-multilingual-mpnet-base-v2` embeddings
- **Chat with Files** — RAG pipeline with OpenAI/Anthropic support
- **Find Similar Files** — vector similarity search endpoint
- **MCP Server** — `python mcp_server.py --stdio` for AI agent integration
- **Unified Search API** — `POST /api/v1/search` with `semantic: true`
- **Remote Access** — `host=0.0.0.0`, CORS `*`
- **Russian i18n** — API + auto-injected translation script
- **Pro gate removed** — all features free

### Bug Fixes
- Fixed `flaskwebgui` browser detection on Windows (Edge child process)
- Fixed Typesense API key format (underscore prefix issue)
- Fixed UnicodeEncodeError on Windows console (cp1251)
- Fixed UI flash on "Recently Indexed" section (cached API responses)

## License

Apache 2.0 (same as original Searchium)
