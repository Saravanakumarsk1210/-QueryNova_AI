import os
import re
import sqlite3
import time
from datetime import datetime, date, time as dt_time
from pathlib import Path
from typing import Any, Optional, Tuple, List, Dict


from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import config

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

# Chat Storage DB Engine
db_url_env = getattr(config, 'DATABASE_URL', '')
if db_url_env and (db_url_env.startswith('postgresql://') or db_url_env.startswith('postgres://')):
    sa_url = db_url_env.replace('postgres://', 'postgresql://')
    if '+' not in sa_url.split('://')[0]:
        try:
            import psycopg
            sa_url = sa_url.replace('postgresql://', 'postgresql+psycopg://')
        except ImportError:
            try:
                import psycopg2
                sa_url = sa_url.replace('postgresql://', 'postgresql+psycopg2://')
            except ImportError:
                pass
    try:
        engine = create_engine(sa_url, pool_pre_ping=True, pool_size=5, max_overflow=10)
    except Exception as _e:
        print(f"[WARN] Failed to create PostgreSQL engine ({_e}), falling back to SQLite")
        DATABASE_URL = f"sqlite:///{config.CHAT_DB_PATH}"
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    DATABASE_URL = f"sqlite:///{config.CHAT_DB_PATH}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    auth0_sub = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(320), nullable=True)
    name = Column(String(200), nullable=True)
    picture = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    chats = relationship("Chat", back_populates="owner")

class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    owner = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at")

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    sender = Column(String(20), nullable=False, default="user") # 'user' or 'assistant'
    role = Column(String(20), nullable=False, default="user")
    query = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    sql = Column(Text, nullable=True)
    sql_query = Column(Text, nullable=True)
    sql_error = Column(Text, nullable=True)
    clarification = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    chat = relationship("Chat", back_populates="messages")

try:
    Base.metadata.create_all(bind=engine)
except Exception as _e:
    print(f"[WARN] Database schema init note: {_e}")

# Ensure schema columns match ORM models
if engine.dialect.name == "sqlite":
    try:
        with engine.connect() as conn:
            res_chats = conn.execute(text("PRAGMA table_info(chats)")).fetchall()
            cols_chats = [r[1] for r in res_chats]
            if "user_id" not in cols_chats:
                conn.execute(text("ALTER TABLE chats ADD COLUMN user_id INTEGER"))

            res_msgs = conn.execute(text("PRAGMA table_info(messages)")).fetchall()
            cols_msgs = [r[1] for r in res_msgs]
            needed_cols = [
                ("sender", "TEXT DEFAULT 'user'"),
                ("role", "TEXT DEFAULT 'user'"),
                ("query", "TEXT"),
                ("content", "TEXT"),
                ("sql", "TEXT"),
                ("sql_query", "TEXT"),
                ("sql_error", "TEXT"),
                ("clarification", "TEXT")
            ]
            for col_name, col_type in needed_cols:
                if col_name not in cols_msgs:
                    conn.execute(text(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}"))
            conn.commit()
    except Exception as e:
        pass




def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class QueryResult(tuple):
    """Backwards-compatible 4-tuple (cols, rows, exec_time_ms, db_err) with dialect metadata."""
    def __new__(cls, cols, rows, exec_time_ms, db_err, dialect_used="postgres", backend="postgres"):
        inst = super().__new__(cls, (cols, rows, exec_time_ms, db_err))
        inst.cols = cols
        inst.rows = rows
        inst.exec_time_ms = exec_time_ms
        inst.db_err = db_err
        inst.dialect = dialect_used
        inst.dialect_used = dialect_used
        inst.backend = backend
        return inst

class TargetDatabaseManager:
    """
    Manages dual-dialect execution against the target learning database.
    Primary: PostgreSQL (rdbms_record) with read-only transaction boundary.
    Fallback: SQLite (NEW DB/redbms_data.db) in read-only mode.
    """
    _pg_available: Optional[bool] = None

    @classmethod
    def get_postgres_connection(cls):
        db_url = getattr(config, 'DATABASE_URL', '')
        # Prefer modern psycopg (v3) with seamless fallback to psycopg2
        try:
            import psycopg
            from psycopg.rows import dict_row
            if db_url and (db_url.startswith('postgresql://') or db_url.startswith('postgres://')):
                raw_url = re.sub(r'^postgres(?:ql)?(?:\+[a-zA-Z0-9_]+)?://', 'postgresql://', db_url)
                return psycopg.connect(raw_url, row_factory=dict_row, connect_timeout=10, autocommit=True)
            else:
                return psycopg.connect(
                    dbname=config.PG_LEARNING_DB,
                    user=config.PG_USER,
                    password=config.PG_PASSWORD,
                    host=config.PG_HOST,
                    port=config.PG_PORT,
                    row_factory=dict_row,
                    connect_timeout=3,
                    autocommit=True
                )
        except ImportError:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            if db_url and (db_url.startswith('postgresql://') or db_url.startswith('postgres://')):
                raw_url = re.sub(r'^postgres(?:ql)?(?:\+[a-zA-Z0-9_]+)?://', 'postgresql://', db_url)
                conn = psycopg2.connect(raw_url, connect_timeout=10)
            else:
                conn = psycopg2.connect(
                    dbname=config.PG_LEARNING_DB,
                    user=config.PG_USER,
                    password=config.PG_PASSWORD,
                    host=config.PG_HOST,
                    port=config.PG_PORT,
                    connect_timeout=3
                )
            conn.set_session(readonly=True, autocommit=True)
            return conn

    @classmethod
    def is_postgres_available(cls) -> bool:
        if cls._pg_available is not None:
            return cls._pg_available
        try:
            conn = cls.get_postgres_connection()
            conn.close()
            cls._pg_available = True
        except Exception:
            cls._pg_available = False
        return cls._pg_available

    @classmethod
    def get_active_backend(cls) -> str:
        pref = getattr(config, 'DB_BACKEND_PREFERENCE', 'auto').lower()
        if pref == 'postgres':
            return 'postgres' if cls.is_postgres_available() else 'sqlite'
        elif pref == 'sqlite':
            return 'sqlite'
        else: # auto
            return 'postgres' if cls.is_postgres_available() else 'sqlite'

    @classmethod
    def get_sqlite_connection(cls):
        db_path = config.TARGET_SQLITE_PATH
        if not db_path.exists():
            candidates = [
                BASE_DIR / "NEW DB" / "redbms_data.db",
                DATA_DIR / "redbms_data.db",
                DATA_DIR / "conference_management.db",
                config.RUNTIME_DIR / "redbms_data.db",
            ]
            for c in candidates:
                if c.exists():
                    db_path = c
                    break
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        # Enforce query-only read safety in SQLite
        try:
            conn.execute("PRAGMA query_only = ON;")
            conn.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            pass
        return conn

    @classmethod
    def execute_query(cls, sql_query: str, limit: int = 1000, force_backend: Optional[str] = None) -> QueryResult:
        """
        Executes a SQL query against PostgreSQL (default) or SQLite fallback.
        Preserves original semantics, applies strict row limit & query timeout.
        """
        start_time = time.time()
        sql_clean = sql_query.strip().rstrip(';')

        # Enforce row limit if not already present
        sql_upper = sql_clean.upper()
        if "LIMIT" not in sql_upper and "COUNT(" not in sql_upper and "FETCH FIRST" not in sql_upper:
            sql_clean += f" LIMIT {limit}"

        backend = force_backend or cls.get_active_backend()

        # Try execution on PostgreSQL
        if backend == 'postgres' and cls.is_postgres_available():
            db_url = getattr(config, 'DATABASE_URL', '')
            if "neon.tech" in str(db_url) or "neon.tech" in str(getattr(config, 'PG_HOST', '')):
                dialect_label = "PostgreSQL (Neon Cloud)"
            else:
                dialect_label = f"PostgreSQL ({getattr(config, 'PG_LEARNING_DB', 'rdbms_record')})"

            try:
                conn = cls.get_postgres_connection()
                is_p3 = hasattr(conn, 'row_factory')
                if is_p3:
                    cur = conn.cursor()
                else:
                    from psycopg2.extras import RealDictCursor
                    cur = conn.cursor(cursor_factory=RealDictCursor)

                with cur:
                    try:
                        cur.execute("SET statement_timeout = 5000;")
                    except Exception:
                        pass
                    cur.execute(sql_clean)
                    if cur.description:
                        cols = [d.name for d in cur.description]
                        raw_rows = cur.fetchall()
                        rows = []
                        for r in raw_rows:
                            row_dict = {}
                            for k, v in dict(r).items():
                                if isinstance(v, (datetime, date, dt_time)):
                                    row_dict[k] = v.isoformat()
                                else:
                                    row_dict[k] = v
                            rows.append(row_dict)
                    else:
                        cols, rows = [], []
                conn.close()
                exec_time_ms = round((time.time() - start_time) * 1000, 2)
                return QueryResult(cols, rows, exec_time_ms, None, dialect_used=dialect_label, backend="postgres")
            except Exception as pg_err:
                exec_time_ms = round((time.time() - start_time) * 1000, 2)
                err_str = str(pg_err)
                # If error is PostgreSQL-specific, return clear diagnostic
                return QueryResult([], [], exec_time_ms, err_str, dialect_used=dialect_label, backend="postgres")

        # Fallback execution on SQLite
        try:
            conn = cls.get_sqlite_connection()
            cursor = conn.cursor()
            cursor.execute(sql_clean)
            rows_raw = cursor.fetchall()
            exec_time_ms = round((time.time() - start_time) * 1000, 2)

            if not rows_raw:
                cols = [d[0] for d in cursor.description] if cursor.description else []
                conn.close()
                return QueryResult(cols, [], exec_time_ms, None, dialect_used="SQLite (NEW DB/redbms_data.db)", backend="sqlite")

            cols = list(rows_raw[0].keys())
            rows = [dict(row) for row in rows_raw]
            conn.close()
            return QueryResult(cols, rows, exec_time_ms, None, dialect_used="SQLite (NEW DB/redbms_data.db)", backend="sqlite")
        except Exception as sl_err:
            exec_time_ms = round((time.time() - start_time) * 1000, 2)
            return QueryResult([], [], exec_time_ms, str(sl_err), dialect_used="SQLite (NEW DB/redbms_data.db)", backend="sqlite")

def log_audit_event(user_id: Any, prompt: str, sql_query: str, status: str, exec_time: float = 0.0, row_count: int = 0):
    """Audit logging for educational SQL learner queries."""
    audit_file = getattr(config, 'RUNTIME_DIR', DATA_DIR) / "audit_log.json"
    import json
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": str(user_id),
        "prompt": prompt,
        "sql_query": sql_query,
        "status": status,
        "exec_time_ms": exec_time,
        "row_count": row_count
    }
    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"[Audit Log Error] {e}")

