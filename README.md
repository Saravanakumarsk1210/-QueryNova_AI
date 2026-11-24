# QueryNova AI — Educational Text-to-SQL & SQL Learning Engine

QueryNova AI is an intelligent, educational Text-to-SQL platform built with Python, FastAPI, and Neon Cloud PostgreSQL (with local SQLite fallback). It guides learners from natural language questions to validated, explained, and executed SQL queries across a relational Conference Management database.

---

## 📁 Project Structure

```
├── api/                                # Vercel Serverless Function entry points
│   └── index.py                        # ASGI handler exposing FastAPI to Vercel
│
├── assets/                             # Project brand assets & diagrams
│   ├── logo.webp                       # QueryNova AI official logo
│   └── schema_diagram.webp             # 5-table conference relational schema diagram
│
├── data/                               # Schema metadata, indices, & local databases
│   ├── chunk_metadata.json             # Lexical & semantic schema chunks for RAG
│   ├── conference_management.db        # Fallback SQLite database
│   ├── knowledge_base.json             # Schema definitions and table relationships
│   ├── redbms_data.db                  # Local relational database file
│   └── schema_ddl.hash                 # SHA-256 hash verifying schema integrity
│
├── docs/                               # System documentation & technical audits
│   └── system_documentation.html       # Visual system architecture documentation
│
├── notebooks/                          # Research & prototyping notebooks
│   └── rag_pipeline_research.ipynb     # Interactive RAG experiment notebook
│
├── tests/                              # Automated test suite (67 tests)
│   ├── test_api_contracts.py           # REST & SSE endpoint contracts
│   ├── test_ast_security.py            # AST SQL security parser & read-only gates
│   ├── test_database_backends.py       # Neon PostgreSQL & SQLite backend switching
│   ├── test_postgresql_features.py     # PostgreSQL CTEs, joins, & window functions
│   ├── test_prompt4_enhancements.py    # Diagnostic explanations & breakdown logic
│   └── test_sql_learner_engine.py      # Typo diagnosis, repair loops, & classification
│
├── web_1/                              # Web frontend interface
│   ├── index.html                      # Main chat application & schema viewer
│   ├── app.js                          # Frontend client logic & SSE stream reader
│   ├── style.css                       # Sunset Orange / Flame Accent dark mode CSS
│   ├── qnsql.webp                      # Frontend logo asset
│   └── schema_diagram.webp             # Frontend schema diagram asset
│
├── ast_security.py                     # Layer 1 AST security validator (read-only policy)
├── auth_routes.py                      # Auth0 authentication integration routes
├── config.py                           # Central configuration & environment loader
├── database.py                         # TargetDatabaseManager & SQLAlchemy chat persistence
├── date_resolver.py                    # Temporal entity resolution (years, dates, quarters)
├── offline_pipeline.py                 # DDL drift hashing & memory ingestion pipeline
├── quality_gate.py                     # SQL semantic preservation & hallucination checks
├── rag_engine.py                       # Hybrid RAG schema retriever with circuit breaker
├── run.py                              # CLI application runner with custom port support
├── server.py                           # FastAPI application & real-time SSE query pipeline
├── sql_learner_engine.py               # 11-stage query classification, diagnosis & repair
│
├── .env.example                        # Template for required environment variables
├── .gitignore                          # Git ignore rules protecting credentials & cache
├── requirements.txt                    # Lean production dependencies for Vercel & local
└── vercel.json                         # Vercel serverless routing configuration
```

---

## 🚀 Quick Start (Local Development)

### 1. Prerequisites
- Python 3.10+
- Active virtual environment (`venv`)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

Key variables:
* `DATABASE_URL`: Neon Cloud PostgreSQL connection string (with `?sslmode=require`).
* `GROQ_API_KEY`: Groq API key for LLM inference (Llama 3.3 / GPT-OSS).

### 4. Start the Application
```bash
python run.py --port 8002
```
Access the application at [http://127.0.0.1:8002](http://127.0.0.1:8002).

---

## 🧪 Running Automated Tests

Run the full automated test suite (67 tests across security, database backends, AST validation, and query repair):
```bash
python -m pytest tests/
```

---

## ☁️ Deployment (Vercel + Neon Cloud)

QueryNova AI is configured for one-click serverless deployment on **Vercel** via `@vercel/python`, optimized with explicit asset bundling and memory pre-caching:

### Vercel Architecture Highlights
- **`vercel.json` Builds Configuration**: Uses `@vercel/python` with explicit `includeFiles` (`web_1/**`, `data/**`, `*.py`, `qnsql.webp`, `schema_diagram.webp`) guaranteeing all static assets and RAG schemas are bundled into the Lambda container.
- **Instant Root Response**: Pre-loads `index.html` into memory to eliminate cold-start filesystem latency and prevent "Cannot GET /" errors.
- **Dedicated Asset Routing**: Explicit endpoints for `/app.js`, `/style.css`, `/qnsql.webp`, and `/schema_diagram.webp` ensure correct MIME types across edge rewrites.
- **Lean Bundle Size**: Uses `.vercelignore` to exclude local tests, caches, and development databases, keeping deployment builds fast and minimal.

### Deployment Steps
1. **Push to GitHub**:
   ```bash
   git push origin main
   ```
2. **Import into Vercel**:
   - Log in to [vercel.com](https://vercel.com) and click **Add New Project**.
   - Import `https://github.com/Saravanakumarsk1210/T2S-`.
   - Leave Framework Preset as **Other** (Vercel automatically detects `vercel.json`).
3. **Configure Environment Variables in Vercel Dashboard**:
   Add the following variables in **Settings > Environment Variables**:
   | Variable | Value / Description |
   |---|---|
   | `DATABASE_URL` | Your Neon Cloud PostgreSQL connection string (`postgresql://...`) |
   | `NEON_API_URL` | Your Neon API REST URL |
   | `GROQ_API_KEY` | Your Groq API key for LLM inference |
   | `TARGET_DB_TYPE` | `postgres` |
   | `DB_BACKEND_PREFERENCE` | `postgres` |
   | `PRIMARY_LLM_MODEL` | `openai/gpt-oss-120b` |
   | `JUDGE_LLM_MODEL` | `openai/gpt-oss-20b` |
   | `FALLBACK_LLM_MODEL` | `qwen/qwen3.8-27b` |
4. **Deploy**:
   - Click **Deploy**. Vercel will build and serve QueryNova AI instantly.
