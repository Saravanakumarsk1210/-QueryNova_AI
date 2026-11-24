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

1. **Push to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit for QueryNova AI"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo-name>.git
   git push -u origin main
   ```
2. **Import into Vercel**:
   - Connect your GitHub repository on [vercel.com](https://vercel.com).
   - Set framework preset to **Other** (Vercel uses `vercel.json` and Python automatically).
   - Add your environment variables from `.env` in the Vercel project settings dashboard.
3. **Deploy**:
   - Vercel automatically deploys the serverless ASGI application via `api/index.py`.
