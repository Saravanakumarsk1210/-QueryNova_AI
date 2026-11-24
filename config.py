import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    pass

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = DATA_DIR / "config"
INDICES_DIR = DATA_DIR / "indices"
RUNTIME_DIR = DATA_DIR / "runtime"
DATASETS_DIR = DATA_DIR / "datasets"

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    INDICES_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_DIR = Path("/tmp/data")
    CONFIG_DIR = DATA_DIR / "config"
    INDICES_DIR = DATA_DIR / "indices"
    RUNTIME_DIR = DATA_DIR / "runtime"
    DATASETS_DIR = DATA_DIR / "datasets"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    INDICES_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)

# Host & Port Configurations
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8002"))

# Database Configurations
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if "channel_binding" in DATABASE_URL:
    import re
    DATABASE_URL = re.sub(r'[?&]channel_binding=[^&]+', '', DATABASE_URL)
    if '?' not in DATABASE_URL and '&' in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace('&', '?', 1)

NEON_API_URL = os.getenv("NEON_API_URL", "").strip()
AWS_ENDPOINT_URL_S3 = os.getenv("AWS_ENDPOINT_URL_S3", "").strip()
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1").strip()

CHAT_DB_PATH = RUNTIME_DIR / "chats.db"
if not CHAT_DB_PATH.exists() and (BASE_DIR / "chats.db").exists():
    CHAT_DB_PATH = BASE_DIR / "chats.db"

# Learning Target Database Configurations
TARGET_DB_TYPE = os.getenv("TARGET_DB_TYPE", "auto")  # 'postgres', 'sqlite', or 'auto'
DB_BACKEND_PREFERENCE = os.getenv("DB_BACKEND_PREFERENCE", "auto")

# Parse DATABASE_URL if available
from urllib.parse import urlparse

if DATABASE_URL and (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")):
    parsed = urlparse(DATABASE_URL)
    PG_HOST = parsed.hostname or os.getenv("PGHOST", "localhost")
    PG_PORT = parsed.port or int(os.getenv("PGPORT", "5432"))
    PG_USER = parsed.username or os.getenv("PGUSER", "postgres")
    PG_PASSWORD = parsed.password or os.getenv("PGPASSWORD", "")
    PG_LEARNING_DB = (parsed.path or "").lstrip("/") or os.getenv("PG_LEARNING_DB", "neondb")
    PG_CHAT_DB = PG_LEARNING_DB
    if DB_BACKEND_PREFERENCE == "auto":
        DB_BACKEND_PREFERENCE = "postgres"
    if TARGET_DB_TYPE == "auto":
        TARGET_DB_TYPE = "postgres"
else:
    # PostgreSQL Learning Database Settings
    PG_HOST = os.getenv("PGHOST", "localhost")
    PG_PORT = int(os.getenv("PGPORT", "5432"))
    PG_USER = os.getenv("PGUSER", "postgres")
    PG_PASSWORD = os.getenv("PGPASSWORD", "")
    PG_LEARNING_DB = os.getenv("PG_LEARNING_DB", "rdbms_record")
    PG_CHAT_DB = os.getenv("PGDATABASE", "t2s_chats")

# Target SQLite DB Path
TARGET_SQLITE_PATH = BASE_DIR / "NEW DB" / "redbms_data.db"
if not TARGET_SQLITE_PATH.exists():
    if (DATA_DIR / "redbms_data.db").exists():
        TARGET_SQLITE_PATH = DATA_DIR / "redbms_data.db"
    elif (DATA_DIR / "conference_management.db").exists():
        TARGET_SQLITE_PATH = DATA_DIR / "conference_management.db"
    elif (RUNTIME_DIR / "redbms_data.db").exists():
        TARGET_SQLITE_PATH = RUNTIME_DIR / "redbms_data.db"

# LLM Providers & Groq Key
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PRIMARY_LLM_MODEL = os.getenv("PRIMARY_LLM_MODEL", "openai/gpt-oss-120b")
JUDGE_LLM_MODEL = os.getenv("JUDGE_LLM_MODEL", "openai/gpt-oss-20b")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "qwen/qwen3.8-27b")
DATASET_DEFAULT_YEAR = int(os.getenv("DATASET_DEFAULT_YEAR", "2023"))

# Paths for Chunk Metadata & Knowledge Base
CHUNK_METADATA_PATH = INDICES_DIR / "chunk_metadata.json"
if not CHUNK_METADATA_PATH.exists() and (DATA_DIR / "chunk_metadata.json").exists():
    CHUNK_METADATA_PATH = DATA_DIR / "chunk_metadata.json"

KNOWLEDGE_BASE_PATH = CONFIG_DIR / "knowledge_base.json"
if not KNOWLEDGE_BASE_PATH.exists() and (DATA_DIR / "knowledge_base.json").exists():
    KNOWLEDGE_BASE_PATH = DATA_DIR / "knowledge_base.json"

# Confidence Floor Thresholds
RETRIEVAL_MIN_CONFIDENCE = float(os.getenv("RETRIEVAL_MIN_CONFIDENCE", "0.35"))
RETRIEVAL_CONFIDENCE_FLOOR = float(os.getenv("RETRIEVAL_CONFIDENCE_FLOOR", "0.35"))
ENTITY_MIN_CONFIDENCE = float(os.getenv("ENTITY_MIN_CONFIDENCE", "0.85"))

# Operational Boundaries
ROW_CAP_LIMIT = int(os.getenv("ROW_CAP_LIMIT", "1000"))
MAX_REFLECTION_RETRIES = int(os.getenv("MAX_REFLECTION_RETRIES", "2"))
CIRCUIT_BREAKER_MAX_FAILURES = int(os.getenv("CIRCUIT_BREAKER_MAX_FAILURES", "3"))
CIRCUIT_BREAKER_RESET_TIMEOUT = int(os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT", "30"))


