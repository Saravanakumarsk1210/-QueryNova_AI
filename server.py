import os
import time
import json
import re
import asyncio
import mimetypes
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

mimetypes.add_type("image/webp", ".webp")

import config
from database import get_db, SessionLocal, Chat, Message, TargetDatabaseManager, log_audit_event
from date_resolver import DateResolver
from ast_security import ASTSecurityGate
from rag_engine import RAGEngine
from quality_gate import QualityGateManager
from offline_pipeline import OfflineKnowledgePipeline
from sql_learner_engine import SQLLearnerEngine

# Initialize FastAPI App
app = FastAPI(title="QueryNova AI - Enterprise Text-to-SQL Platform", version="2.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = config.BASE_DIR / "web_1"
try:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

from auth_routes import configure_auth
configure_auth(app)

# Models for Pydantic Body Validation
class QueryRequest(BaseModel):
    query: str

class SQLExecuteRequest(BaseModel):
    sql: str
    limit: Optional[int] = config.ROW_CAP_LIMIT

class CreateChatRequest(BaseModel):
    title: Optional[str] = "New QueryNova Chat"

class UpdateChatRequest(BaseModel):
    title: str

@app.on_event("startup")
def startup_event():
    """App startup trigger: verifies DDL hash & checks schema vector index."""
    print("=" * 70)
    print("[INIT] Starting QueryNova AI on Port 8002 - Conference Management DB...")
    print("[THEME] UI Theme: Sunset Orange / Flame Accent Dark Mode")
    print("[SECURITY] Layer 1 AST Parser + Layer 2 Read-Only DB Role")
    print("=" * 70)
    OfflineKnowledgePipeline.check_and_reindex_if_needed()
    OfflineKnowledgePipeline.consume_agent_memory_feedback()

# ── REST ENDPOINTS ──

def _chat_to_dict(c: Chat) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }

def _message_to_dict(m: Message) -> dict:
    role = m.sender if hasattr(m, 'sender') and m.sender else ('user' if m.query else 'assistant')
    content = m.content or m.query or ""
    return {
        "id": m.id,
        "role": role,
        "sender": role,
        "content": content,
        "query": m.query or content,
        "sql": m.sql_query,
        "sql_query": m.sql_query,
        "sql_error": m.sql_error,
        "clarification": m.clarification if hasattr(m, 'clarification') else None,
        "created_at": m.created_at.isoformat() if m.created_at else None
    }

@app.get("/api/chats")
@app.get("/api/chats/")
@app.get("/api/v1/chats")
@app.get("/api/v1/chats/")
def list_chats(db: Session = Depends(get_db)):
    chats = db.query(Chat).order_by(Chat.updated_at.desc()).all()
    result = []
    for c in chats:
        last_msg = db.query(Message).filter(Message.chat_id == c.id).order_by(Message.created_at.desc()).first()
        preview = last_msg.query or last_msg.content if last_msg else "New Conversation"
        cd = _chat_to_dict(c)
        cd["last_message_preview"] = preview
        result.append(cd)
    return {"chats": result}

@app.post("/api/chats")
@app.post("/api/chats/")
@app.post("/api/v1/chats")
@app.post("/api/v1/chats/")
def create_chat(req: CreateChatRequest, db: Session = Depends(get_db)):
    chat = Chat(title=req.title or "New QueryNova Chat")
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return _chat_to_dict(chat)

@app.get("/api/chats/{chat_id}")
@app.get("/api/chats/{chat_id}/")
@app.get("/api/v1/chats/{chat_id}")
@app.get("/api/v1/chats/{chat_id}/")
def get_chat_history(chat_id: Any, db: Session = Depends(get_db)):
    try:
        c_id = int(chat_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail=f"Invalid chat ID: {chat_id}")
    chat = db.query(Chat).filter(Chat.id == c_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = db.query(Message).filter(Message.chat_id == c_id).order_by(Message.created_at.asc()).all()
    return {
        "chat": _chat_to_dict(chat),
        "messages": [_message_to_dict(m) for m in messages]
    }

@app.get("/api/chats/{chat_id}/messages")
@app.get("/api/chats/{chat_id}/messages/")
def get_chat_messages(chat_id: int, db: Session = Depends(get_db)):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at.asc()).all()
    return {
        "chat": _chat_to_dict(chat),
        "messages": [_message_to_dict(m) for m in messages]
    }

@app.post("/api/chats/{chat_id}")
@app.post("/api/chats/{chat_id}/")
@app.put("/api/chats/{chat_id}")
@app.put("/api/chats/{chat_id}/")
@app.patch("/api/chats/{chat_id}")
@app.patch("/api/chats/{chat_id}/")
@app.post("/api/chats/{chat_id}/title")
@app.post("/api/chats/{chat_id}/title/")
@app.put("/api/chats/{chat_id}/title")
@app.put("/api/chats/{chat_id}/title/")
@app.post("/api/v1/chats/{chat_id}")
@app.post("/api/v1/chats/{chat_id}/")
@app.put("/api/v1/chats/{chat_id}")
@app.put("/api/v1/chats/{chat_id}/")
@app.patch("/api/v1/chats/{chat_id}")
@app.patch("/api/v1/chats/{chat_id}/")
def update_chat_title(chat_id: Any, req: UpdateChatRequest, db: Session = Depends(get_db)):
    try:
        c_id = int(chat_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid chat ID: {chat_id}")
    chat = db.query(Chat).filter(Chat.id == c_id).first()
    title_val = req.title.strip()[:200] if req.title and req.title.strip() else "New chat"
    if not chat:
        chat = Chat(id=c_id, title=title_val)
        db.add(chat)
    else:
        chat.title = title_val
        chat.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(chat)
    return _chat_to_dict(chat)

@app.delete("/api/chats/{chat_id}")
@app.delete("/api/chats/{chat_id}/")
@app.delete("/api/v1/chats/{chat_id}")
@app.delete("/api/v1/chats/{chat_id}/")
def delete_chat(chat_id: Any, db: Session = Depends(get_db)):
    try:
        c_id = int(chat_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail=f"Invalid chat ID: {chat_id}")
    chat = db.query(Chat).filter(Chat.id == c_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.delete(chat)
    db.commit()
    return {"ok": True}

@app.delete("/api/chats/{chat_id}/messages/from/{message_id}")
@app.delete("/api/chats/{chat_id}/messages/from/{message_id}/")
@app.delete("/api/v1/chats/{chat_id}/messages/from/{message_id}")
@app.delete("/api/v1/chats/{chat_id}/messages/from/{message_id}/")
def delete_messages_from(chat_id: Any, message_id: Any, db: Session = Depends(get_db)):
    try:
        c_id = int(chat_id)
        m_id = int(message_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid parameters")
    chat = db.query(Chat).filter(Chat.id == c_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.query(Message).filter(Message.chat_id == c_id, Message.id >= m_id).delete(synchronize_session=False)
    chat.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}

@app.post("/api/execute-sql")
@app.post("/api/v1/execute-sql")
def execute_sql_endpoint(req: SQLExecuteRequest):
    """Executes raw SQL query with AST Security validation and row capping."""
    valid, msg = ASTSecurityGate.validate_sql(req.sql)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)
        
    res = TargetDatabaseManager.execute_query(req.sql, limit=req.limit or config.ROW_CAP_LIMIT)
    cols, rows, exec_time, db_err = res
    if db_err:
        raise HTTPException(status_code=400, detail=db_err)
        
    return {
        "columns": cols,
        "rows": rows,
        "data": rows,
        "execution_time_ms": exec_time,
        "row_count": len(rows),
        "dialect": getattr(res, 'dialect', 'Database')
    }

@app.post("/api/diagnose-sql")
@app.post("/api/v1/diagnose-sql")
def diagnose_sql_endpoint(req: SQLExecuteRequest):
    """Diagnoses and corrects SQL queries using the educational learner engine."""
    res = SQLLearnerEngine.diagnose_and_execute(req.sql)
    return res

# ── MAIN SSE QUERY PIPELINE ENDPOINT ──

@app.post("/api/chats/{chat_id}/query")
@app.post("/api/v1/chats/{chat_id}/query")
async def process_chat_query_sse(chat_id: int, req: QueryRequest):
    """
    Guarded 11-Stage Online Execution Engine with real-time SSE streaming ticks.
    """
    user_query = req.query.strip()
    
    async def sse_event_generator():
        def sse_pack(event_type: str, data: dict) -> str:
            payload = {"type": event_type, **data}
            return f"data: {json.dumps(payload)}\n\n"

        def _save_messages(sql_val, summary_val, error_val=None, clarification_val=None):
            try:
                c_session = SessionLocal()
                c_id_int = int(chat_id)
                chat_record = c_session.query(Chat).filter(Chat.id == c_id_int).first()
                if not chat_record:
                    title_text = user_query[:40] if len(user_query) <= 40 else user_query[:37] + "..."
                    chat_record = Chat(id=c_id_int, title=title_text)
                    c_session.add(chat_record)
                    c_session.commit()
                c_session.add(Message(chat_id=c_id_int, sender="user", role="user", query=user_query))
                c_session.add(Message(chat_id=c_id_int, sender="assistant", role="assistant", sql_query=sql_val, sql_error=error_val, clarification=clarification_val, content=summary_val))
                c_session.commit()
                c_session.close()
            except Exception as log_err:
                print(f"[Audit Log Warning] Non-fatal log error: {log_err}")

        try:
            # ── INTENT CLASSIFICATION ──
            classification = SQLLearnerEngine.classify_input(user_query)
            category = classification["category"]
            extracted_sql = classification["extracted_sql"] or user_query

            # ── WORKFLOW 0: CONVERSATIONAL CHIT-CHAT ──
            if category == "CHIT_CHAT":
                greeting_text = (
                    "Hello! I am **QueryNova AI**, your interactive SQL tutor for the Conference Management database.\n\n"
                    "You can:\n"
                    "- **Ask questions in plain English** (e.g. *\"Show all rooms with capacity > 100\"* or *\"Which companies have the most attendees?\"*)\n"
                    "- **Paste any PostgreSQL SQL query** to validate and execute it directly\n"
                    "- **Submit incorrect SQL** to receive immediate error diagnosis, minimal single-delta repairs, and clause-by-clause explanations."
                )
                _save_messages(None, greeting_text, None)
                yield sse_pack("result", {
                    "result": {
                        "request_type": "chit_chat",
                        "status": "success",
                        "sql": None,
                        "sql_error": None,
                        "summary": greeting_text,
                        "explanation": greeting_text,
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "execution_time_ms": 0.0,
                        "dialect": TargetDatabaseManager.get_active_backend().capitalize()
                    }
                })
                return

            # ── DEDICATED SQL LEARNER WORKFLOW (Direct SQL, Explain SQL, Fix SQL) ──
            if category in ["DIRECT_SQL", "EXPLAIN_SQL", "FIX_SQL"]:
                target_sql_input = extracted_sql if category in ["EXPLAIN_SQL", "FIX_SQL"] else user_query
                yield sse_pack("progress", {"step_id": "security_sanitize", "status": "start", "label": "1. SQL Validation: Checking Syntax & Relations"})
                await asyncio.sleep(0.04)

                diagnostic = await asyncio.to_thread(SQLLearnerEngine.diagnose_and_execute, target_sql_input)
                diag_status = diagnostic.get("status")

                if diag_status == "clarification":
                    yield sse_pack("progress", {"step_id": "security_sanitize", "status": "done", "label": "1. Incomplete Clause Detected"})
                    yield sse_pack("progress", {"step_id": "error_identification", "status": "warning", "label": "2. Incomplete Query: Clarification Required"})
                    yield sse_pack("progress", {"step_id": "summarize", "status": "done", "label": "3. Clarification Formulated"})

                    _save_messages(None, diagnostic["explanation"], diagnostic.get("error_identified"), clarification_val=diagnostic.get("clarification"))

                    yield sse_pack("result", {
                        "result": {
                            **diagnostic,
                            "sql_error": diagnostic.get("error_identified")
                        }
                    })
                    return

                elif diag_status == "valid":
                    yield sse_pack("progress", {"step_id": "security_sanitize", "status": "done", "label": "1. SQL Validation: Query is Valid"})
                    yield sse_pack("progress", {"step_id": "error_identification", "status": "done", "label": "2. No Errors Found"})
                    yield sse_pack("progress", {"step_id": "sql_correction", "status": "done", "label": "3. No Correction Required"})
                    yield sse_pack("progress", {"step_id": "quality_gate", "status": "done", "label": "4. Quality & Safety Passed"})
                    yield sse_pack("progress", {"step_id": "db_execution", "status": "done", "label": f"5. Executed Cleanly in {diagnostic['execution_time_ms']} ms ({len(diagnostic['rows'])} rows)"})
                    yield sse_pack("progress", {"step_id": "summarize", "status": "done", "label": "6. Output Ready"})

                    _save_messages(diagnostic.get("sql"), diagnostic["explanation"], None)
                    log_audit_event("guest", user_query, diagnostic.get("sql") or "", "VALID_SQL", diagnostic.get("execution_time_ms", 0.0), len(diagnostic.get("rows", [])))

                    yield sse_pack("result", {
                        "result": {
                            **diagnostic,
                            "sql_error": None
                        }
                    })
                    return

                elif diag_status == "security_rejected":
                    err_lbl = (diagnostic.get("error_identified") or "Security Policy Violation")[:45]
                    yield sse_pack("progress", {"step_id": "security_sanitize", "status": "error", "label": "1. AST Security Gate: Policy Violation"})
                    yield sse_pack("progress", {"step_id": "error_identification", "status": "error", "label": f"2. Security Block: {err_lbl}"})
                    yield sse_pack("progress", {"step_id": "quality_gate", "status": "error", "label": "3. Statement Blocked in Read-Only Sandbox"})
                    yield sse_pack("progress", {"step_id": "summarize", "status": "done", "label": "4. Security Guidance Formulated"})

                    _save_messages(None, diagnostic["explanation"], diagnostic.get("error_identified"))
                    log_audit_event("guest", user_query, diagnostic.get("error_identified") or "", "SECURITY_REJECTED", 0.0, 0)

                    yield sse_pack("result", {
                        "result": {
                            **diagnostic,
                            "sql_error": diagnostic.get("error_identified")
                        }
                    })
                    return

                else: # "corrected" or "error"
                    err_lbl = (diagnostic.get("error_identified") or "Relation / syntax mistake")[:45]
                    corr_lbl = (diagnostic.get("corrected_sql") or "")[:40]

                    yield sse_pack("progress", {"step_id": "security_sanitize", "status": "done", "label": "1. SQL Validation Complete"})
                    yield sse_pack("progress", {"step_id": "error_identification", "status": "done", "label": f"2. Error Identified: {err_lbl}"})
                    yield sse_pack("progress", {"step_id": "sql_correction", "status": "done", "label": f"3. Minimal Correction: {corr_lbl}"})
                    yield sse_pack("progress", {"step_id": "quality_gate", "status": "done", "label": "4. Corrected Query Safety Verified"})
                    yield sse_pack("progress", {"step_id": "db_execution", "status": "done", "label": f"5. Executed Corrected Query ({len(diagnostic.get('rows', []))} rows)"})
                    yield sse_pack("progress", {"step_id": "summarize", "status": "done", "label": "6. Educational Feedback Formulated"})

                    _save_messages(diagnostic.get("sql"), diagnostic["explanation"], diagnostic.get("error_identified"))
                    log_audit_event("guest", user_query, diagnostic.get("sql") or "", "CORRECTED_SQL", diagnostic.get("execution_time_ms", 0.0), len(diagnostic.get("rows", [])))

                    yield sse_pack("result", {
                        "result": {
                            **diagnostic,
                            "sql_error": diagnostic.get("error_identified")
                        }
                    })
                    return

            # ── NATURAL LANGUAGE TEXT-TO-SQL PIPELINE ──
            # Stage 1: Ingestion & Auth Pre-Filter
            yield sse_pack("progress", {"step_id": "security_sanitize", "status": "start", "label": "1. Sanitizing & Pre-Filtering Prompt"})
            await asyncio.sleep(0.05)
            
            # Check NL keyword malicious attempt
            if re.search(r'\b(DROP|DELETE|TRUNCATE|ALTER|GRANT)\b', user_query, re.I):
                yield sse_pack("progress", {"step_id": "security_sanitize", "status": "error", "label": "Security Violation: Prohibited DDL keyword"})
                yield sse_pack("result", {"result": {"sql": None, "sql_error": "Security Violation: Prohibited DDL keyword in query prompt.", "summary": "Query blocked due to security rules."}})
                return

            # Check out-of-scope domain queries
            q_lower = user_query.lower()
            if re.search(r'\b(weather|temperature|forecast|sports score|stock price)\b', q_lower):
                out_msg = "This assistant is configured for the Conference Management Database (attendees, companies, presentations, rooms, and attendance records); general live queries are out of scope."
                _save_messages(None, out_msg, "Out of Scope Question")
                yield sse_pack("progress", {"step_id": "security_sanitize", "status": "error", "label": "Out of Scope Question"})
                yield sse_pack("result", {"result": {"sql": None, "sql_error": "Out of Scope Question", "summary": out_msg}})
                return

            yield sse_pack("progress", {"step_id": "security_sanitize", "status": "done", "label": "1. Prompt Sanitized"})

            # Stage 2: Fast Follow-Up Rewriter Cache (Zero-LLM Path)
            yield sse_pack("progress", {"step_id": "fast_cache", "status": "start", "label": "2. Checking Fast Follow-Up Rewriter Cache"})
            db = SessionLocal()
            last_msg = db.query(Message).filter(Message.chat_id == chat_id, Message.sql_query.isnot(None)).order_by(Message.created_at.desc()).first()
            db.close()

            resolved_date = DateResolver.resolve_date_phrase(user_query)
            
            if last_msg and last_msg.sql_query and resolved_date and resolved_date.get("resolved") and len(user_query.split()) <= 6:
                # Fast follow-up date shift regex rewrite
                old_sql = last_msg.sql_query
                new_date_clause = resolved_date.get('sql_clause') or resolved_date.get('clause', '')
                rewritten_sql = re.sub(r'(?:DATE\(start_time\)|start_time)\s+(?:BETWEEN\s+\'[^\']+\'\s+AND\s+\'[^\']+\'|=\s+\'[^\']+\')', new_date_clause, old_sql, flags=re.I)
                
                if rewritten_sql != old_sql:
                    yield sse_pack("progress", {"step_id": "fast_cache", "status": "done", "label": "2. Fast Follow-Up Cache Hit (0 ms LLM Latency)"})
                    
                    # Execute on DB
                    cols, rows, exec_time, db_err = TargetDatabaseManager.execute_query(rewritten_sql)
                    matched_label = resolved_date.get('matched_phrase') or 'requested period'
                    summary_text = f"Retrieved {len(rows)} records for {matched_label} via fast cache rewrite."
                    
                    # Log Message
                    cls_session = SessionLocal()
                    cls_session.add(Message(chat_id=chat_id, sender="user", role="user", query=user_query))
                    cls_session.add(Message(chat_id=chat_id, sender="assistant", role="assistant", sql_query=rewritten_sql, content=summary_text))
                    cls_session.commit()
                    cls_session.close()
                    
                    log_audit_event("guest", user_query, rewritten_sql, "SUCCESS_CACHE", exec_time, len(rows))
                    
                    yield sse_pack("result", {
                        "result": {
                            "sql": rewritten_sql,
                            "sql_error": None,
                            "columns": cols,
                            "rows": rows,
                            "execution_time_ms": exec_time,
                            "summary": summary_text
                        }
                    })
                    return

            yield sse_pack("progress", {"step_id": "fast_cache", "status": "done", "label": "2. Cache Check Complete"})

            # Stage 3: Deterministic Date Phrase Resolution
            yield sse_pack("progress", {"step_id": "date_resolver", "status": "start", "label": "3. Resolving Deterministic Date Bounds"})
            date_clause_str = ""
            if resolved_date and resolved_date.get("resolved"):
                clause_val = resolved_date.get('sql_clause') or resolved_date.get('clause', '')
                matched_phrase = resolved_date.get('matched_phrase') or 'Date filter'
                date_clause_str = f"Date Constraint: Enforce `{clause_val}` in WHERE clause.\n"
                yield sse_pack("progress", {"step_id": "date_resolver", "status": "done", "label": f"3. Resolved Date: {matched_phrase}"})
            else:
                yield sse_pack("progress", {"step_id": "date_resolver", "status": "done", "label": "3. No Date Constraint Required"})

            # Stage 4: Hybrid RAG Search & Retrieval Confidence Floor
            yield sse_pack("progress", {"step_id": "hybrid_rag", "status": "start", "label": "4. Hybrid FAISS + BM25 Schema Retrieval"})
            schema_chunks, max_rrf_score, is_weak = RAGEngine.search_schema(user_query, top_k=5)
            
            if is_weak:
                yield sse_pack("progress", {"step_id": "hybrid_rag", "status": "error", "label": f"Weak Retrieval Score ({max_rrf_score} < {config.RETRIEVAL_CONFIDENCE_FLOOR})"})
                summary_text = "I couldn't find a strong schema match for your request. Could you please specify if you are asking about attendees, presentations, rooms, companies, or attendance?"
                _save_messages(None, summary_text, "Retrieval Confidence Floor Unmet")
                yield sse_pack("result", {"result": {"sql": None, "sql_error": "Retrieval Confidence Floor Unmet", "summary": summary_text}})
                return

            yield sse_pack("progress", {"step_id": "hybrid_rag", "status": "done", "label": f"4. Retrieved Top-5 Schema Chunks (Score: {max_rrf_score})"})

            # Stage 5: Domain-Constrained Dialect SQL Synthesis
            yield sse_pack("progress", {"step_id": "sql_generation", "status": "start", "label": "5. Synthesizing Dialect SQL via Groq API"})
            
            schema_context = "\n\n".join([c['chunk_text'] for c in schema_chunks])
            active_backend = TargetDatabaseManager.get_active_backend()
            dialect_name = "PostgreSQL" if active_backend == "postgres" else "SQLite"
            
            system_prompt = (
                f"You are an expert Text-to-SQL AI Engineer for the Conference Management System.\n"
                f"Generate ONLY a single valid {dialect_name} SELECT query enclosed inside <sql>...</sql> tags.\n\n"
                "CRITICAL DATABASE ARCHITECTURE & SCHEMA RULES:\n"
                "1. Output ONLY a SELECT statement inside <sql>...</sql> tags. No markdown code blocks, explanation, or commentary outside <sql>...</sql>.\n"
                "2. The database has 5 normalized tables:\n"
                "   - attendee (attendee_id, first_name, last_name, phone, email, vip)\n"
                "     * vip is VARCHAR(4), values are 'yes' or 'no'\n"
                "     * phone and email may be NULL\n"
                "   - room (room_id, floor_number, seat_capacity)\n"
                "   - company (company_id, name, description, primary_contact_attendee_id)\n"
                "     * primary_contact_attendee_id references attendee(attendee_id)\n"
                "   - presentation (presentation_id, booked_company_id, booked_room_id, start_time, end_time)\n"
                "     * booked_company_id references company(company_id)\n"
                "     * booked_room_id references room(room_id)\n"
                "     * start_time, end_time are TIMESTAMPs formatted 'YYYY-MM-DD HH:MM:SS'\n"
                "   - presentation_attendance (ticket_id, presentation_id, attendee_id)\n"
                "     * presentation_id references presentation(presentation_id)\n"
                "     * attendee_id references attendee(attendee_id)\n"
            )
            if active_backend == "postgres":
                system_prompt += (
                    "3. Use STRICT PostgreSQL SQL dialect:\n"
                    "   - Use DATE_TRUNC('month', start_time) for monthly grouping.\n"
                    "   - Use start_time::date for dates, EXTRACT(YEAR FROM start_time) for year.\n"
                    "   - Use ILIKE for case-insensitive string matching.\n"
                    "   - Use CURRENT_DATE / NOW() for current timestamps.\n"
                )
            else:
                system_prompt += (
                    "3. Use STRICT SQLite SQL dialect ONLY:\n"
                    "   - Use DATE(start_time) for dates, strftime('%Y', start_time) for year, strftime('%m', start_time) for month.\n"
                    "   - Use strftime('%H:%M', start_time) for time of day.\n"
                    "   - DO NOT use PostgreSQL EXTRACT() or MySQL functions.\n"
                )
            system_prompt += (
                "4. COMMON QUERY PATTERNS & JOINS:\n"
                "   - VIP attendees: WHERE LOWER(vip) = 'yes'\n"
                "   - Presentations with company: presentation JOIN company ON presentation.booked_company_id = company.company_id\n"
                "   - Presentations with room: presentation JOIN room ON presentation.booked_room_id = room.room_id\n"
                "   - Attendance count per presentation: SELECT p.presentation_id, COUNT(pa.ticket_id) FROM presentation p LEFT JOIN presentation_attendance pa ON p.presentation_id = pa.presentation_id GROUP BY p.presentation_id\n"
                "   - Attendees registered for presentations: presentation_attendance pa JOIN attendee a ON pa.attendee_id = a.attendee_id\n"
                "   - Primary contact of company: company c JOIN attendee a ON c.primary_contact_attendee_id = a.attendee_id\n"
                "5. Enforce `LIMIT 100` on list/non-aggregate queries.\n"
                f"{date_clause_str}\n"
                f"SCHEMA CONTEXT:\n{schema_context}"
            )
            
            # Generation & Bounded Reflection Retry Loop (Max 2 Retries)
            current_attempt = 0
            generated_sql = ""
            is_passed = False
            feedback_reason = ""
            reflection_prompt_extra = ""

            while current_attempt <= config.MAX_REFLECTION_RETRIES:
                current_attempt += 1
                prompt_input = user_query + reflection_prompt_extra
                
                try:
                    raw_llm_out = RAGEngine.call_llm_with_circuit_breaker(system_prompt, prompt_input, temperature=0.1)
                    sql_match = re.search(r'<sql>(.*?)</sql>', raw_llm_out, re.DOTALL | re.IGNORECASE)
                    if sql_match:
                        generated_sql = sql_match.group(1).strip()
                    else:
                        generated_sql = raw_llm_out.strip()
                except Exception as llm_err:
                    yield sse_pack("progress", {"step_id": "sql_generation", "status": "error", "label": f"LLM Generation Error: {str(llm_err)}"})
                    _save_messages(None, "LLM Provider call failed.", str(llm_err))
                    yield sse_pack("result", {"result": {"sql": None, "sql_error": str(llm_err), "summary": "LLM Provider call failed."}})
                    return

                # Stage 6 & 7: AST Security Gate & 4-Tier Quality Gate + Independent LLM Judge
                is_passed, feedback_reason, sanitized_sql = QualityGateManager.validate_and_judge_sql(user_query, generated_sql)
                generated_sql = sanitized_sql
                
                if is_passed:
                    break
                else:
                    yield sse_pack("progress", {"step_id": "quality_gate", "status": "warning", "label": f"Attempt {current_attempt} Failed: {feedback_reason}. Retrying Reflection Loop..."})
                    reflection_prompt_extra = f"\n\nPREVIOUS ERROR: Your prior generated SQL failed validation: {feedback_reason}. Correct the query strictly."

            if not is_passed:
                yield sse_pack("progress", {"step_id": "quality_gate", "status": "error", "label": "Terminal Failure: Reflection Loop Exceeded (Max 2 Retries)"})
                summary_text = "I couldn't generate a reliable, validated query for this request. Please check column or date parameters."
                _save_messages(generated_sql, summary_text, feedback_reason)
                yield sse_pack("result", {"result": {"sql": generated_sql, "sql_error": feedback_reason, "summary": summary_text}})
                return

            yield sse_pack("progress", {"step_id": "quality_gate", "status": "done", "label": "6. Passed AST Security Gate & Independent LLM Judge"})

            # Stage 8: DB Execution on SELECT-Only Role
            yield sse_pack("progress", {"step_id": "db_execution", "status": "start", "label": f"7. Executing on SELECT-Only Role ({dialect_name})"})
            res = await asyncio.to_thread(TargetDatabaseManager.execute_query, generated_sql)
            cols, rows, exec_time, db_err = res
            
            if db_err:
                yield sse_pack("progress", {"step_id": "db_execution", "status": "error", "label": f"DB Error: {db_err}"})
                summary_text = "Database execution encountered an error."
                _save_messages(generated_sql, summary_text, db_err)
                yield sse_pack("result", {"result": {"sql": generated_sql, "sql_error": db_err, "summary": summary_text, "dialect": getattr(res, 'dialect', 'Database')}})
                return

            yield sse_pack("progress", {"step_id": "db_execution", "status": "done", "label": f"7. Executed Cleanly in {exec_time} ms ({len(rows)} rows returned)"})

            # Stage 9: Natural Language Executive Summarization
            yield sse_pack("progress", {"step_id": "summarize", "status": "start", "label": "8. Generating Executive Plain English Summary"})
            
            row_count = len(rows)
            sample_limit = 50 if row_count <= 50 else 25
            rows_sample = rows[:sample_limit]

            sum_system_prompt = (
                "You are an executive event analytics assistant for the Conference Management System.\n"
                "Summarize the database results in clear, accurate plain English for conference coordinators and executive leadership.\n"
                "STRICT RULES:\n"
                "1. Max 2-3 sentences. Be factual and precise.\n"
                f"2. Total records returned in query result: {row_count}. Base overall counts on {row_count}, NOT on the sample size.\n"
                "3. Explicitly highlight any VIPs, companies, room capacities, presentation schedules, or non-standard values found.\n"
                "4. Do NOT mention SQL, tables, dict, JSON, or technical system terms."
            )
            sum_user_prompt = f"User Question: '{user_query}'\nTotal Records Returned: {row_count}\nData Rows (first {len(rows_sample)} of {row_count}):\n{json.dumps(rows_sample)}"
            
            try:
                summary_text = await asyncio.to_thread(RAGEngine.call_llm_with_circuit_breaker, sum_system_prompt, sum_user_prompt, 0.1)
            except Exception:
                summary_text = f"Retrieved {len(rows)} record(s) matching your conference query."

            yield sse_pack("progress", {"step_id": "summarize", "status": "done", "label": "8. Summary Synthesized"})

            # Log Session & Audit (Fail-safe)
            _save_messages(generated_sql, summary_text, None)
            log_audit_event("guest", user_query, generated_sql, "SUCCESS", exec_time, len(rows))

            # Return Final SSE Result
            yield sse_pack("result", {
                "result": {
                    "request_type": "nl_to_sql",
                    "status": "valid",
                    "sql": generated_sql,
                    "sql_error": None,
                    "columns": cols,
                    "rows": rows,
                    "row_count": len(rows),
                    "execution_time_ms": exec_time,
                    "summary": summary_text,
                    "explanation": summary_text,
                    "clause_breakdown": SQLLearnerEngine.generate_clause_breakdown(generated_sql),
                    "dialect": getattr(res, 'dialect', 'Database')
                }
            })

        except Exception as err:
            import traceback
            traceback.print_exc()
            yield sse_pack("progress", {"step_id": "error", "status": "error", "label": f"Pipeline Error: {str(err)}"})
            yield sse_pack("result", {
                "result": {
                    "sql": None,
                    "sql_error": str(err),
                    "summary": f"Query execution error: {str(err)}"
                }
            })


    return StreamingResponse(sse_event_generator(), media_type="text/event-stream")

# ── EXPLICIT STATIC & ROOT ROUTES (Modeled after EXPENSE TRACKER for robust Vercel serverless delivery) ──
INDEX_HTML_PATH = WEB_DIR / "index.html"
_index_html_cache: str = ""
if INDEX_HTML_PATH.exists():
    try:
        _index_html_cache = INDEX_HTML_PATH.read_text(encoding="utf-8")
    except Exception as _e:
        print(f"[WARN] Could not pre-read index.html: {_e}")

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def serve_root():
    global _index_html_cache
    if _index_html_cache:
        return HTMLResponse(content=_index_html_cache, media_type="text/html; charset=utf-8")
    if INDEX_HTML_PATH.exists():
        return FileResponse(str(INDEX_HTML_PATH), media_type="text/html; charset=utf-8")
    return HTMLResponse("<h1>QueryNova AI</h1><p>Frontend assets loading...</p>", status_code=200)

@app.get("/app.js")
def serve_app_js():
    p = WEB_DIR / "app.js"
    if p.exists():
        return FileResponse(str(p), media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")

@app.get("/style.css")
def serve_style_css():
    p = WEB_DIR / "style.css"
    if p.exists():
        return FileResponse(str(p), media_type="text/css")
    raise HTTPException(status_code=404, detail="style.css not found")

@app.get("/qnsql.webp")
@app.get("/logo.webp")
def serve_logo():
    for p in [WEB_DIR / "qnsql.webp", config.BASE_DIR / "qnsql.webp", config.BASE_DIR / "assets" / "logo.webp"]:
        if p.exists():
            return FileResponse(str(p), media_type="image/webp")
    raise HTTPException(status_code=404, detail="Logo not found")

@app.get("/schema_diagram.webp")
def serve_schema_diagram():
    for p in [WEB_DIR / "schema_diagram.webp", config.BASE_DIR / "schema_diagram.webp", config.BASE_DIR / "assets" / "schema_diagram.webp"]:
        if p.exists():
            return FileResponse(str(p), media_type="image/webp")
    raise HTTPException(status_code=404, detail="Schema diagram not found")

@app.get("/favicon.ico")
def serve_favicon():
    for p in [WEB_DIR / "qnsql.webp", config.BASE_DIR / "qnsql.webp"]:
        if p.exists():
            return FileResponse(str(p), media_type="image/webp")
    return Response(status_code=204)

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=config.HOST, port=config.PORT, reload=True)
