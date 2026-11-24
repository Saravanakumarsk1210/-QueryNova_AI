"""
Automated Regression and Compliance Tests for MASTER PROMPT 4 — QueryNova AI
Covers:
1. Intent Classification (NL vs Direct SQL vs Explain SQL vs Fix SQL vs Chit-Chat)
2. Standardized Diagnostic Contract & Schema Preservation
3. Clause Breakdown Generator for PostgreSQL
4. Visual Diff Calculation
5. Semantic Preservation & Loop/Cycle Prevention
6. Zero-Row Execution Transparency
7. NULL Value Preservation & Format Integrity
8. AST Read-Only Security Verification
"""

import pytest
from sql_learner_engine import SQLLearnerEngine
from database import TargetDatabaseManager
from ast_security import ASTSecurityGate


# ─────────────────────────────────────────────────────────────
# 1. INTENT CLASSIFICATION TESTS
# ─────────────────────────────────────────────────────────────

def test_intent_classification_natural_language_with_sql_words():
    """Natural language questions containing words like 'show', 'select', 'from', 'company' must NOT be classified as direct SQL."""
    nl_queries = [
        "Show presentations from company X",
        "Can you select rooms with seat capacity greater than 50?",
        "List all attendees from attendee table",
        "Which presentations have the highest attendance?",
        "Find records within date range 2026-11-01 to 2026-11-05",
        "How many attendees are registered for each room?",
        "Tell me the primary contact for company Google",
        "Give me the attendance count for presentation 1"
    ]
    for q in nl_queries:
        res = SQLLearnerEngine.classify_input(q)
        assert res["category"] == "NL_QUESTION", f"Query '{q}' should be classified as NL_QUESTION, got {res['category']}"
        assert SQLLearnerEngine.is_sql_query(q) is False, f"is_sql_query('{q}') should return False"


def test_intent_classification_direct_sql():
    """Pasted SQL queries (valid or invalid) must be classified as DIRECT_SQL."""
    sql_queries = [
        "SELECT * FROM room;",
        "SELECT * FROM rooms;",
        "SELECT first_name, last_name FROM attendee WHERE vip = 'yes'",
        "WITH cte AS (SELECT attendee_id FROM attendee) SELECT * FROM cte",
        "```sql\nSELECT room_id FROM room\n```",
        "JOIN attendee WITH company",
        "selct * from room"  # typo keyword
    ]
    for q in sql_queries:
        res = SQLLearnerEngine.classify_input(q)
        assert res["category"] == "DIRECT_SQL", f"Query '{q}' should be classified as DIRECT_SQL, got {res['category']}"
        assert SQLLearnerEngine.is_sql_query(q) is True, f"is_sql_query('{q}') should return True"


def test_intent_classification_explain_and_fix_requests():
    """Explicit requests to explain or fix SQL must be recognized with extracted SQL."""
    explain_res = SQLLearnerEngine.classify_input("Explain query: SELECT * FROM room")
    assert explain_res["category"] == "EXPLAIN_SQL"
    assert explain_res["extracted_sql"] == "SELECT * FROM room"

    explain_res2 = SQLLearnerEngine.classify_input("Walk me through this SQL: SELECT attendee_id FROM attendee")
    assert explain_res2["category"] == "EXPLAIN_SQL"
    assert explain_res2["extracted_sql"] == "SELECT attendee_id FROM attendee"

    fix_res = SQLLearnerEngine.classify_input("Fix this SQL: SELECT * FROM rooms")
    assert fix_res["category"] == "FIX_SQL"
    assert fix_res["extracted_sql"] == "SELECT * FROM rooms"


def test_intent_classification_chit_chat():
    """Conversational greetings and general queries must be classified as CHIT_CHAT, not SQL."""
    greetings = ["hi", "hello", "hey there", "who are you", "what can you do", "help"]
    for g in greetings:
        res = SQLLearnerEngine.classify_input(g)
        assert res["category"] == "CHIT_CHAT", f"'{g}' should be CHIT_CHAT, got {res['category']}"
        assert SQLLearnerEngine.is_sql_query(g) is False


# ─────────────────────────────────────────────────────────────
# 2. STANDARDIZED DIAGNOSTIC CONTRACT TESTS
# ─────────────────────────────────────────────────────────────

def test_diagnostic_contract_on_valid_sql():
    """Valid SQL execution must return the complete standardized contract."""
    sql = "SELECT room_id, seat_capacity FROM room WHERE seat_capacity > 50;"
    diag = SQLLearnerEngine.diagnose_and_execute(sql)

    assert diag["request_type"] == "sql_execution"
    assert diag["status"] == "valid"
    assert diag["is_valid"] is True
    assert diag["original_sql"] == sql
    assert diag["corrected_sql"] is None
    assert diag["sql"] == sql.rstrip(";")
    assert diag["error_identified"] is None
    assert isinstance(diag["clause_breakdown"], dict)
    assert "SELECT" in diag["clause_breakdown"]
    assert "FROM" in diag["clause_breakdown"]
    assert "WHERE" in diag["clause_breakdown"]
    assert isinstance(diag["columns"], list)
    assert isinstance(diag["rows"], list)
    assert diag["row_count"] == len(diag["rows"])
    assert diag["execution_time_ms"] >= 0.0
    assert "dialect" in diag
    # Ensure explanation does NOT contain raw markdown code-fence boilerplate
    assert "```sql" not in diag["explanation"]


def test_diagnostic_contract_on_table_typo():
    """Table typo (e.g. rooms -> room) must return complete diagnostic metadata and minimal correction."""
    sql = "SELECT * FROM rooms;"
    diag = SQLLearnerEngine.diagnose_and_execute(sql)

    assert diag["request_type"] == "sql_diagnostic"
    assert diag["status"] == "corrected"
    assert diag["error_category"] == "table_typo"
    assert diag["semantic_guard"] == "safe_mechanical"
    assert diag["original_sql"] == sql
    assert diag["corrected_sql"] == "SELECT * FROM room"
    assert "rooms" in diag["error_identified"].lower()
    assert "room" in diag["error_identified"].lower()
    assert diag["diff"]["has_changes"] is True
    assert len(diag["diff"]["changes"]) > 0
    assert diag["row_count"] == 10
    assert len(diag["rows"]) == 10


def test_diagnostic_contract_on_column_typo():
    """Column typo (e.g. firstname -> first_name) must be corrected minimally."""
    sql = "SELECT firstname FROM attendee;"
    diag = SQLLearnerEngine.diagnose_and_execute(sql)

    assert diag["status"] == "corrected"
    assert diag["error_category"] == "column_typo"
    assert diag["corrected_sql"] == "SELECT first_name FROM attendee"
    assert "firstname" in diag["error_identified"].lower()
    assert "first_name" in diag["error_identified"].lower()
    assert len(diag["rows"]) > 0


def test_diagnostic_contract_on_incomplete_clause():
    """Trailing WHERE clause must trigger a clarification request without guessing values."""
    sql = "SELECT * FROM room WHERE"
    diag = SQLLearnerEngine.diagnose_and_execute(sql)

    assert diag["request_type"] == "clarification"
    assert diag["status"] == "clarification"
    assert diag["error_category"] == "incomplete_clause"
    assert diag["semantic_guard"] == "ambiguous_clarification"
    assert diag["corrected_sql"] is None
    assert diag["clarification"] is not None
    assert "condition" in diag["clarification"].lower()
    assert diag["rows"] == []


# ─────────────────────────────────────────────────────────────
# 3. CLAUSE BREAKDOWN GENERATOR TESTS
# ─────────────────────────────────────────────────────────────

def test_clause_breakdown_comprehensive():
    """Validates clause breakdown parsing for multi-clause SQL."""
    sql = (
        "WITH high_capacity AS (SELECT room_id, seat_capacity FROM room WHERE seat_capacity > 50) "
        "SELECT room_id, COUNT(*) FROM high_capacity "
        "GROUP BY room_id HAVING COUNT(*) >= 1 "
        "ORDER BY room_id ASC LIMIT 5;"
    )
    breakdown = SQLLearnerEngine.generate_clause_breakdown(sql)

    assert "WITH" in breakdown
    assert "high_capacity" in breakdown["WITH"]
    assert "SELECT" in breakdown
    assert "FROM" in breakdown
    assert "GROUP BY" in breakdown
    assert "HAVING" in breakdown
    assert "ORDER BY" in breakdown
    assert "LIMIT" in breakdown
    assert "5" in breakdown["LIMIT"]


def test_clause_breakdown_join():
    """Validates clause breakdown for JOIN statements."""
    sql = "SELECT * FROM presentation JOIN company ON presentation.booked_company_id = company.company_id;"
    breakdown = SQLLearnerEngine.generate_clause_breakdown(sql)

    assert "FROM" in breakdown
    assert "JOIN" in breakdown
    assert "company" in breakdown["JOIN"]
    assert "booked_company_id" in breakdown["JOIN"]


# ─────────────────────────────────────────────────────────────
# 4. VISUAL DIFF CALCULATION TESTS
# ─────────────────────────────────────────────────────────────

def test_compute_sql_diff():
    """Visual diff must identify exact substituted tokens."""
    diff = SQLLearnerEngine.compute_sql_diff("SELECT * FROM rooms;", "SELECT * FROM room;")
    assert diff["has_changes"] is True
    assert len(diff["changes"]) == 1
    ch = diff["changes"][0]
    assert ch["from"] == "rooms"
    assert ch["to"] == "room"

    diff_ident = SQLLearnerEngine.compute_sql_diff("SELECT * FROM room", "SELECT * FROM room")
    assert diff_ident["has_changes"] is False
    assert diff_ident["changes"] == []


# ─────────────────────────────────────────────────────────────
# 5. ZERO-ROW HANDLING AND NULL PRESERVATION TESTS
# ─────────────────────────────────────────────────────────────

def test_zero_row_valid_query_handling():
    """A query returning 0 rows is completely valid and must NOT be marked as an error."""
    sql = "SELECT * FROM room WHERE seat_capacity > 99999;"
    diag = SQLLearnerEngine.diagnose_and_execute(sql)

    assert diag["status"] == "valid"
    assert diag["is_valid"] is True
    assert diag["rows"] == []
    assert diag["row_count"] == 0
    assert "0 rows" in diag["explanation"].lower()
    assert "not an sql error" in diag["explanation"].lower()


def test_null_value_preservation_in_database():
    """TargetDatabaseManager must preserve NULL values as None in Python rather than empty string."""
    res = TargetDatabaseManager.execute_query("SELECT attendee_id, phone FROM attendee LIMIT 10;")
    cols, rows, exec_time, db_err = res
    assert db_err is None
    assert len(rows) > 0
    # Every row is a dictionary preserving native types
    for r in rows:
        assert isinstance(r, dict)
        assert "attendee_id" in r
        assert "phone" in r


# ─────────────────────────────────────────────────────────────
# 6. AST SECURITY GATE TESTS
# ─────────────────────────────────────────────────────────────

def test_security_blocks_destructive_ddl_and_dml():
    """AST Security Gate must reject DROP, DELETE, ALTER, and stacked queries."""
    blocked_statements = [
        "DROP TABLE room;",
        "ALTER TABLE attendee ADD COLUMN test INT;",
        "TRUNCATE TABLE presentation;",
        "SELECT * FROM room; DROP TABLE room;",
        "DELETE FROM attendee WHERE attendee_id = 1;"
    ]
    for stmt in blocked_statements:
        valid, msg = ASTSecurityGate.validate_sql(stmt)
        assert valid is False, f"Statement '{stmt}' should have been rejected by AST security"



# ─────────────────────────────────────────────────────────────
# 7. SQL LEARNER ENGINE SECURITY & SEMANTIC HARDENING TESTS
# ─────────────────────────────────────────────────────────────

def test_learner_engine_security_rejects_drop():
    """SQLLearnerEngine must reject DROP statements with security_rejected status."""
    res = SQLLearnerEngine.diagnose_and_execute("DROP TABLE room;")
    assert res["status"] == "security_rejected"
    assert res["error_category"] == "prohibited_operation"
    assert res["semantic_guard"] == "security_rejected"
    assert res["corrected_sql"] is None
    assert "DROP" in res["error_identified"]


def test_learner_engine_security_rejects_stacked_queries():
    """SQLLearnerEngine must reject stacked/multiple statements with security_rejected status."""
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM room; DROP TABLE attendee;")
    assert res["status"] == "security_rejected"
    assert res["error_category"] == "multiple_statements"
    assert res["semantic_guard"] == "security_rejected"
    assert res["corrected_sql"] is None
    assert "multiple statements" in res["error_identified"].lower()


def test_learner_engine_security_rejects_scoped_and_unscoped_dml():
    """SQLLearnerEngine must reject DML statements and offer safe read-only preview."""
    # Scoped DELETE
    res_scoped = SQLLearnerEngine.diagnose_and_execute("DELETE FROM attendee WHERE attendee_id = 1;")
    assert res_scoped["status"] == "security_rejected"
    assert res_scoped["error_category"] == "scoped_dml"
    assert "SELECT * FROM attendee WHERE attendee_id = 1;" in res_scoped["corrected_sql"]

    # Unscoped DELETE
    res_unscoped = SQLLearnerEngine.diagnose_and_execute("DELETE FROM attendee;")
    assert res_unscoped["status"] == "security_rejected"
    assert res_unscoped["error_category"] == "unscoped_dml"
    assert "SELECT * FROM attendee" in res_unscoped["corrected_sql"]


def test_learner_engine_ambiguous_indirect_join_clarification():
    """Joining presentation and attendee without FK must return clarification, NOT a Cartesian product."""
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM presentation JOIN attendee;")
    assert res["status"] == "clarification"
    assert res["error_category"] == "ambiguous_join"
    assert res["semantic_guard"] == "ambiguous_clarification"
    assert res["corrected_sql"] is None
    assert res["clarification"] is not None
    assert "presentation_attendance" in res["learning_tip"]
    assert "company" in res["learning_tip"]


def test_learner_engine_rejects_cartesian_product_on_1_equals_1():
    """Queries with ON 1=1 between non-direct FK tables must trigger ambiguous join clarification."""
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM presentation JOIN attendee ON 1=1;")
    assert res["status"] == "clarification"
    assert res["error_category"] == "ambiguous_join"
    assert res["corrected_sql"] is None


def test_learner_engine_cartesian_join_with_known_fk_corrected():
    """Queries with ON 1=1 between direct FK tables must minimally correct the ON condition."""
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM attendee JOIN company ON 1=1;")
    assert res["status"] == "corrected"
    assert res["error_category"] == "join_condition"
    assert "primary_contact_attendee_id = attendee.attendee_id" in res["corrected_sql"]


def test_learner_engine_select_keyword_typo_correction():
    """Typo in the leading SELECT keyword (e.g. selct) must be corrected minimally."""
    res = SQLLearnerEngine.diagnose_and_execute("selct * from room;")
    assert res["status"] == "corrected"
    assert res["corrected_sql"] == "SELECT * from room"
    assert res["error_category"] == "syntax_error"
