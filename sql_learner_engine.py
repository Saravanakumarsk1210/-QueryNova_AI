import re
import json
import sqlite3
import time
from typing import Dict, Any, Tuple, Optional, List
import config
from database import TargetDatabaseManager
from ast_security import ASTSecurityGate

# Table schema details
SCHEMA_TABLES = {
    "attendee": {
        "columns": ["attendee_id", "first_name", "last_name", "phone", "email", "vip"],
        "primary_key": ["attendee_id"],
        "foreign_keys": [],
        "synonyms": {
            "id": "attendee_id",
            "attendeeid": "attendee_id",
            "firstname": "first_name",
            "fname": "first_name",
            "first": "first_name",
            "lastname": "last_name",
            "lname": "last_name",
            "last": "last_name",
            "mobile": "phone",
            "cell": "phone",
            "telephone": "phone",
            "phone_number": "phone",
            "phonenumber": "phone",
            "contact": "phone",
            "mail": "email",
            "email_address": "email",
            "vip_status": "vip",
            "is_vip": "vip"
        }
    },
    "room": {
        "columns": ["room_id", "floor_number", "seat_capacity"],
        "primary_key": ["room_id"],
        "foreign_keys": [],
        "synonyms": {
            "id": "room_id",
            "roomid": "room_id",
            "room_number": "room_id",
            "capacity": "seat_capacity",
            "seats": "seat_capacity",
            "seating_capacity": "seat_capacity",
            "size": "seat_capacity",
            "floor": "floor_number",
            "floornumber": "floor_number",
            "level": "floor_number"
        }
    },
    "company": {
        "columns": ["company_id", "name", "description", "primary_contact_attendee_id"],
        "primary_key": ["company_id"],
        "foreign_keys": [
            {
                "column": "primary_contact_attendee_id",
                "references_table": "attendee",
                "references_column": "attendee_id"
            }
        ],
        "synonyms": {
            "id": "company_id",
            "companyid": "company_id",
            "company_name": "name",
            "companyname": "name",
            "cname": "name",
            "title": "name",
            "desc": "description",
            "details": "description",
            "primary_contact": "primary_contact_attendee_id",
            "primary_contact_id": "primary_contact_attendee_id",
            "contact_attendee_id": "primary_contact_attendee_id",
            "contact_id": "primary_contact_attendee_id",
            "attendee_id": "primary_contact_attendee_id"
        }
    },
    "presentation": {
        "columns": ["presentation_id", "booked_company_id", "booked_room_id", "start_time", "end_time"],
        "primary_key": ["presentation_id"],
        "foreign_keys": [
            {
                "column": "booked_company_id",
                "references_table": "company",
                "references_column": "company_id"
            },
            {
                "column": "booked_room_id",
                "references_table": "room",
                "references_column": "room_id"
            }
        ],
        "synonyms": {
            "id": "presentation_id",
            "presentationid": "presentation_id",
            "company_id": "booked_company_id",
            "companyid": "booked_company_id",
            "booked_company": "booked_company_id",
            "room_id": "booked_room_id",
            "roomid": "booked_room_id",
            "booked_room": "booked_room_id",
            "startdate": "start_time",
            "start_date": "start_time",
            "starttime": "start_time",
            "start": "start_time",
            "enddate": "end_time",
            "end_date": "end_time",
            "endtime": "end_time",
            "end": "end_time"
        }
    },
    "presentation_attendance": {
        "columns": ["ticket_id", "presentation_id", "attendee_id"],
        "primary_key": ["ticket_id"],
        "foreign_keys": [
            {
                "column": "presentation_id",
                "references_table": "presentation",
                "references_column": "presentation_id"
            },
            {
                "column": "attendee_id",
                "references_table": "attendee",
                "references_column": "attendee_id"
            }
        ],
        "synonyms": {
            "id": "ticket_id",
            "ticket": "ticket_id",
            "ticketid": "ticket_id",
            "attendance_id": "ticket_id"
        }
    }
}

TABLE_SYNONYMS = {
    "rooms": "room",
    "attendees": "attendee",
    "companies": "company",
    "presentations": "presentation",
    "attendance": "presentation_attendance",
    "attendances": "presentation_attendance",
    "presentation_attendances": "presentation_attendance",
    "tickets": "presentation_attendance"
}

ALL_VALID_TABLES = list(SCHEMA_TABLES.keys())

class SQLLearnerEngine:
    """
    SQL Diagnostic & Minimal Correction Engine for Learners.
    Workflow:
    1. Detect SQL input & classify intent
    2. SQL validation (syntax, tables, columns, constraints)
    3. Error identification
    4. Minimal SQL correction with semantic preservation guards
    5. Execute corrected query on target DB
    6. Return structured diagnostic contract & pedagogical feedback
    """

    @classmethod
    def classify_input(cls, text: str) -> Dict[str, Any]:
        """
        Robustly classifies user input into one of:
        - 'DIRECT_SQL': Pure SQL query or SQL intent to execute/diagnose.
        - 'EXPLAIN_SQL': Request to explain an SQL query.
        - 'FIX_SQL': Request to debug or fix an SQL query.
        - 'NL_QUESTION': Natural language question asking for Text-to-SQL.
        - 'CHIT_CHAT': Conversational greetings or non-database queries.
        - 'AMBIGUOUS': Mixed or unclear intent.
        """
        if not text or not text.strip():
            return {"category": "AMBIGUOUS", "extracted_sql": None, "clean_text": ""}

        raw = text.strip()
        # Strip outer markdown SQL fences if present
        fenced_match = re.match(r'^```(?:sql)?\s*([\s\S]*?)\s*```$', raw, re.I)
        if fenced_match:
            sql_inside = fenced_match.group(1).strip()
            return {"category": "DIRECT_SQL", "extracted_sql": sql_inside, "clean_text": sql_inside}

        clean = raw
        # 1. Greetings / Chit-Chat (e.g. "hi", "hello", "hey", "hey there", "who are you")
        if re.match(r'^(?:hi|hello|hey(?:\s+there)?|good\s+(?:morning|afternoon|evening)|howdy|who\s+are\s+you|what\s+can\s+you\s+do|help)\b[?!.]*$', clean, re.I):
            return {"category": "CHIT_CHAT", "extracted_sql": None, "clean_text": clean}

        # 2. Explicit SQL Explanation Request: e.g. "Explain query: SELECT * FROM room"
        explain_match = re.match(
            r'^(?:explain|describe|analyze|walk\s+me\s+through|breakdown)\s+(?:the\s+|this\s+)?(?:query|sql)?\s*[:\s]+([\s\S]+)$',
            clean,
            re.I
        )
        if explain_match:
            candidate_sql = explain_match.group(1).strip()
            if re.match(r'^(?:SELECT|WITH|INSERT|UPDATE|DELETE|JOIN)\b', candidate_sql, re.I):
                return {"category": "EXPLAIN_SQL", "extracted_sql": candidate_sql, "clean_text": candidate_sql}

        # 3. Explicit SQL Fix Request: e.g. "Fix this SQL: SELECT * FROM rooms"
        fix_match = re.match(
            r'^(?:fix|correct|debug|diagnose)\s+(?:the\s+|this\s+)?(?:query|sql)?\s*[:\s]+([\s\S]+)$',
            clean,
            re.I
        )
        if fix_match:
            candidate_sql = fix_match.group(1).strip()
            return {"category": "FIX_SQL", "extracted_sql": candidate_sql, "clean_text": candidate_sql}

        # 4. Natural Language questions starting with inquiry/conversational verbs
        # e.g. "Show presentations from company X", "Can you list attendees?", "Which room has..."
        is_sql_show = bool(re.match(r'^SHOW\s+(?:TABLES|DATABASES|COLUMNS|ALL|[a-zA-Z_]+)\s*;?$', clean, re.I))
        nl_starters = r'^(?:show|find|which|who|how|what|list|tell\s+me|can\s+you|could\s+you|please|give\s+me|display|get\s+me|count)\b'
        if re.match(nl_starters, clean, re.I) and not is_sql_show:
            return {"category": "NL_QUESTION", "extracted_sql": None, "clean_text": clean}

        # 5. Direct SQL keywords at the start
        if re.match(r'^(?:SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|EXPLAIN|DESCRIBE)\b', clean, re.I):
            return {"category": "DIRECT_SQL", "extracted_sql": clean, "clean_text": clean}

        # 6. Typo in leading SELECT keyword: selct, slect, selec, slecet
        if re.match(r'^(?:selct|slect|selec|slecet|selcet)\b', clean, re.I):
            return {"category": "DIRECT_SQL", "extracted_sql": clean, "clean_text": clean}

        # 7. SQL JOIN shorthand: "JOIN attendee WITH company", "NATURAL JOIN attendee"
        if re.match(r'^(?:JOIN|NATURAL\s+JOIN)\b', clean, re.I) or re.match(r'^JOIN\s+\w+\s+(?:WITH|AND)\s+\w+', clean, re.I):
            return {"category": "DIRECT_SQL", "extracted_sql": clean, "clean_text": clean}

        # 8. Structural SQL patterns: Rigid SELECT <projection> FROM <table...> without question phrasing
        if not clean.endswith('?') and not re.search(r'\b(i want|i need|can you|how do)\b', clean, re.I):
            if re.search(r'^\s*SELECT\s+[\s\S]+?\s+FROM\s+[a-zA-Z0-9_]+', clean, re.I):
                return {"category": "DIRECT_SQL", "extracted_sql": clean, "clean_text": clean}

        # Default to NL_QUESTION
        return {"category": "NL_QUESTION", "extracted_sql": None, "clean_text": clean}

    @classmethod
    def is_sql_query(cls, text: str) -> bool:
        """Determines if the learner's input is a SQL query or SQL intent."""
        classification = cls.classify_input(text)
        return classification["category"] in ["DIRECT_SQL", "EXPLAIN_SQL", "FIX_SQL"]

    @classmethod
    def compute_sql_diff(cls, original_sql: str, corrected_sql: str) -> Dict[str, Any]:
        """
        Computes token/word-level diff between original and corrected queries
        to enable accessible, side-by-side or inline visual diffing in the UI.
        """
        orig_clean = (original_sql or "").strip()
        corr_clean = (corrected_sql or "").strip()
        if orig_clean == corr_clean:
            return {
                "original": orig_clean,
                "corrected": corr_clean,
                "has_changes": False,
                "changes": []
            }

        import difflib
        orig_words = re.findall(r'[a-zA-Z0-9_]+|[^\s\w]', orig_clean)
        corr_words = re.findall(r'[a-zA-Z0-9_]+|[^\s\w]', corr_clean)
        matcher = difflib.SequenceMatcher(None, orig_words, corr_words)

        changes = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != 'equal':
                old_frag = " ".join(orig_words[i1:i2])
                new_frag = " ".join(corr_words[j1:j2])
                changes.append({
                    "tag": tag,
                    "from": old_frag,
                    "to": new_frag
                })

        return {
            "original": orig_clean,
            "corrected": corr_clean,
            "has_changes": True,
            "changes": changes
        }

    @classmethod
    def generate_clause_breakdown(cls, sql: str) -> Dict[str, str]:
        """
        Generates pedagogical clause-by-clause explanations for learners.
        Grounds explanations in the active conference database schema.
        """
        if not sql or not sql.strip():
            return {}

        breakdown = {}
        clean = sql.strip().rstrip(';')

        # WITH clause (CTEs)
        with_match = re.search(r'^\s*WITH\s+([a-zA-Z0-9_]+)\s+AS\s*\(([\s\S]+?)\)', clean, re.I)
        if with_match:
            cte_name = with_match.group(1)
            breakdown["WITH"] = f"Defines a Common Table Expression (CTE) named `{cte_name}` as a temporary, reusable result set."

        # SELECT clause
        select_match = re.search(r'\bSELECT\s+(DISTINCT\s+)?([\s\S]+?)\s+FROM\b', clean, re.I)
        if select_match:
            is_distinct = bool(select_match.group(1))
            cols_str = select_match.group(2).strip()
            distinct_note = " (removing duplicate rows)" if is_distinct else ""
            if cols_str == "*":
                breakdown["SELECT"] = f"Projects all columns (`*`){distinct_note} from the queried table(s)."
            elif "COUNT(*)" in cols_str.upper():
                breakdown["SELECT"] = f"Calculates row counts using `COUNT(*)`{distinct_note} for the requested projection."
            else:
                breakdown["SELECT"] = f"Projects specific column(s): `{cols_str}`{distinct_note}."
        elif re.search(r'\bSELECT\b', clean, re.I):
            breakdown["SELECT"] = "Specifies which columns or aggregate expressions to retrieve from the database."

        # FROM clause
        from_match = re.search(r'\bFROM\s+([a-zA-Z0-9_]+)', clean, re.I)
        if from_match:
            tbl = from_match.group(1).lower()
            tbl_real = TABLE_SYNONYMS.get(tbl, tbl)
            descriptions = {
                "attendee": "the conference attendees table (storing attendee IDs, names, emails, and VIP flags)",
                "room": "the conference rooms table (storing room IDs, floor numbers, and seat capacities)",
                "company": "the sponsoring companies table (storing company IDs, names, and contact IDs)",
                "presentation": "the conference presentations table (storing presentation IDs, booked rooms, booked companies, and schedules)",
                "presentation_attendance": "the attendance junction table (mapping attendees to attended presentations via tickets)"
            }
            tbl_desc = descriptions.get(tbl_real, f"the `{tbl_real}` table")
            breakdown["FROM"] = f"Designates {tbl_desc} as the primary source of records."

        # JOIN clauses
        join_matches = re.findall(r'\b((?:INNER\s+|LEFT\s+|RIGHT\s+|CROSS\s+)?JOIN)\s+([a-zA-Z0-9_]+)\s*(?:ON\s+([^\n\r;]+?)(?=(?:\s+(?:JOIN|WHERE|GROUP\s+BY|ORDER\s+BY|LIMIT)|\s*;?\s*$)))?', clean, re.I)
        if join_matches:
            join_descs = []
            for j_type, j_tbl, j_on in join_matches:
                j_clean_type = j_type.strip().upper()
                j_tbl_clean = j_tbl.strip()
                if j_on and j_on.strip():
                    join_descs.append(f"{j_clean_type} with `{j_tbl_clean}` matching foreign key condition `ON {j_on.strip()}`")
                else:
                    join_descs.append(f"{j_clean_type} with `{j_tbl_clean}`")
            breakdown["JOIN"] = "Combines related tables: " + "; ".join(join_descs) + "."

        # WHERE clause
        where_match = re.search(r'\bWHERE\s+([\s\S]+?)(?=(?:\s+(?:GROUP\s+BY|ORDER\s+BY|LIMIT)|\s*;?\s*$))', clean, re.I)
        if where_match:
            cond = where_match.group(1).strip()
            breakdown["WHERE"] = f"Filters rows prior to aggregation: includes only records satisfying `{cond}`."

        # GROUP BY clause
        group_match = re.search(r'\bGROUP\s+BY\s+([\s\S]+?)(?=(?:\s+(?:HAVING|ORDER\s+BY|LIMIT)|\s*;?\s*$))', clean, re.I)
        if group_match:
            grp = group_match.group(1).strip()
            breakdown["GROUP BY"] = f"Aggregates rows sharing identical values in `{grp}` to compute summary values per group."

        # HAVING clause
        having_match = re.search(r'\bHAVING\s+([\s\S]+?)(?=(?:\s+(?:ORDER\s+BY|LIMIT)|\s*;?\s*$))', clean, re.I)
        if having_match:
            hav = having_match.group(1).strip()
            breakdown["HAVING"] = f"Filters aggregated groups: retains only groups meeting condition `{hav}`."

        # ORDER BY clause
        order_match = re.search(r'\bORDER\s+BY\s+([\s\S]+?)(?=(?:\s+LIMIT|\s*;?\s*$))', clean, re.I)
        if order_match:
            ord_col = order_match.group(1).strip()
            breakdown["ORDER BY"] = f"Orders output rows by `{ord_col}`."

        # LIMIT clause
        limit_match = re.search(r'\bLIMIT\s+(\d+)', clean, re.I)
        if limit_match:
            lim = limit_match.group(1)
            breakdown["LIMIT"] = f"Caps the returned result set to at most {lim} row(s)."

        return breakdown

    @classmethod
    def diagnose_and_execute(cls, query: str) -> Dict[str, Any]:
        """
        Diagnoses learner query, applies minimal correction if needed,
        executes against the target database, and returns structured feedback.
        Enforces AST security boundary and iterative multi-error diagnosis.
        """
        raw_query = re.sub(r'^```(?:sql)?\s*|\s*```$', '', query.strip(), flags=re.I).strip()
        clean_query = raw_query.rstrip(';')

        # Check for leading keyword typo in SELECT (e.g. "selct * from room")
        norm_query = raw_query
        leading_sel_typo = re.match(r'^(?:selct|slect|selec|slecet|selcet)\b', clean_query, re.I)
        if leading_sel_typo:
            norm_query = re.sub(r'^(?:selct|slect|selec|slecet|selcet)\b', 'SELECT', raw_query, flags=re.I)

        # Handle Natural Language JOIN shorthand ONLY if NOT starting with SELECT or WITH
        if not re.match(r'^\s*(SELECT|WITH)\b', raw_query, re.I) and not leading_sel_typo:
            nl_join = cls._check_join_shorthand(raw_query)
            if nl_join:
                return cls._execute_and_package(
                    original_sql=raw_query,
                    corrected_sql=nl_join["corrected_sql"],
                    error_identified=nl_join["error_identified"],
                    explanation=nl_join["explanation"],
                    is_valid=False,
                    error_category="join_condition",
                    semantic_guard="schema_unique"
                )

        # --- STEP 0: AST Security Gate Verification (Hard Boundary) ---
        is_safe, sec_msg = ASTSecurityGate.validate_sql(norm_query)
        if not is_safe:
            return cls._handle_security_violation(raw_query, clean_query, sec_msg)

        # --- STEP 1: Check for incomplete clauses (WHERE, ORDER BY, GROUP BY, HAVING, trailing AND/OR) ---
        incomplete_feedback = cls._check_incomplete_clauses(raw_query, clean_query)
        if incomplete_feedback:
            return incomplete_feedback

        # --- STEP 2: Educational Check for Unscoped / Scoped Destructive Statements ---
        destructive_feedback = cls._check_destructive_dml(raw_query)
        if destructive_feedback:
            return destructive_feedback

        # --- STEP 3: Check for Cartesian product anti-pattern: ON 1=1 or ON TRUE ---
        if re.search(r'\bON\s+(?:1\s*=\s*1|TRUE|1)\b', clean_query, re.I):
            join_match = re.search(r'\bFROM\s+([a-zA-Z0-9_]+)\s+(?:INNER\s+|LEFT\s+|RIGHT\s+)?JOIN\s+([a-zA-Z0-9_]+)', clean_query, re.I)
            if join_match:
                t1 = TABLE_SYNONYMS.get(join_match.group(1).lower(), join_match.group(1).lower())
                t2 = TABLE_SYNONYMS.get(join_match.group(2).lower(), join_match.group(2).lower())
                fk_on = cls._get_fk_join_condition(t1, t2)
                if fk_on:
                    corr_sql = re.sub(r'\bON\s+(?:1\s*=\s*1|TRUE|1)\b', f'ON {fk_on}', clean_query, flags=re.I)
                    err = "Cartesian Product Anti-Pattern: 'ON 1=1' performs an unconditional CROSS JOIN, matching every record of both tables indiscriminately."
                    tip = f"> **Why Join Conditions Matter:** An `ON` condition must link tables via foreign keys (e.g. `ON {fk_on}`) rather than `1=1`."
                    return cls._execute_and_package(
                        original_sql=raw_query,
                        corrected_sql=corr_sql,
                        error_identified=err,
                        explanation=tip,
                        is_valid=False,
                        error_category="join_condition",
                        semantic_guard="schema_unique"
                    )
                else:
                    return cls._handle_ambiguous_join(raw_query, clean_query, t1, t2)

        # --- STEP 4: First Check: Does original query execute cleanly? ---
        # Check if missing ON in JOIN
        has_missing_on = cls._is_missing_join_on(clean_query)
        # Check if anti-patterns exist
        has_anti_patterns = (
            "==" in clean_query or
            re.search(r'(!=|<>|=)\s*NULL\b', clean_query, re.I) or
            "=>" in clean_query or
            "=<" in clean_query or
            bool(re.search(r'\bON\s+(?:1\s*=\s*1|TRUE|1)\b', clean_query, re.I)) or
            bool(re.search(r'\bSELECT\s+FROM\b', clean_query, re.I)) or
            bool(re.search(r'\bSELECT\s+\*\s+(?!FROM\b)[a-zA-Z0-9_]+\b', clean_query, re.I)) or
            re.search(r'\bTOTAL\s*\(\s*\*\s*\)', clean_query, re.I) or
            re.search(r'\bLIMIT\s+-\d+', clean_query, re.I) or
            # Missing GROUP BY when mixing non-agg with COUNT(*)
            (bool(re.search(r'\b(COUNT|SUM|AVG|MIN|MAX)\s*\(', clean_query, re.I)) and
             bool(re.search(r'\bSELECT\s+[a-zA-Z0-9_]+\s*,\s*(?:COUNT|SUM|AVG|MIN|MAX)\b', clean_query, re.I)) and
             "GROUP BY" not in clean_query.upper()) or
            # Multi-row scalar subquery = (SELECT ...)
            bool(re.search(r'=\s*\(\s*SELECT\b(?!.*LIMIT\s+1\b)', clean_query, re.I | re.DOTALL))
        )

        if not has_missing_on and not has_anti_patterns:
            res = TargetDatabaseManager.execute_query(clean_query)
            cols, rows, exec_time, db_err = res
            dialect_used = getattr(res, 'dialect', 'Database')
            if db_err is None:
                # Query is valid! Zero rows returned is NOT an error.
                row_count = len(rows)
                clause_breakdown = cls.generate_clause_breakdown(clean_query)
                if row_count > 0:
                    explanation = f"Your SQL query is syntactically and semantically valid. It executed cleanly on {dialect_used} and retrieved {row_count} record(s)."
                else:
                    explanation = f"Your SQL query is syntactically and semantically valid. It executed cleanly on {dialect_used} and returned 0 rows. (Zero rows returned is not an SQL error; no records matched your filter criteria)."

                return {
                    "request_type": "sql_execution",
                    "status": "valid",
                    "error_category": None,
                    "semantic_guard": "valid",
                    "is_valid": True,
                    "original_sql": raw_query,
                    "corrected_sql": None,
                    "sql": clean_query,
                    "error_identified": None,
                    "learning_tip": "Query executed cleanly without modifications.",
                    "clause_breakdown": clause_breakdown,
                    "diff": {"original": raw_query, "corrected": clean_query, "has_changes": False, "changes": []},
                    "clarification": None,
                    "summary": explanation,
                    "explanation": explanation,
                    "columns": cols,
                    "rows": rows,
                    "row_count": row_count,
                    "execution_time_ms": exec_time,
                    "dialect": dialect_used
                }

        # --- STEP 5: Multi-Pass Iterative Repair Loop (Fixes Multiple Mistakes) ---
        MAX_PASSES = 4
        current_sql = clean_query
        seen_queries = {clean_query.lower()}
        errors_collected = []
        tips_collected = []
        detected_categories = []

        for pass_num in range(MAX_PASSES):
            prev_pass_sql = current_sql

            # 0. Typo in SELECT keyword: selct, slect, selec, slecet, selcet
            if re.match(r'^(?:selct|slect|selec|slecet|selcet)\b', current_sql, re.I):
                current_sql = re.sub(r'^(?:selct|slect|selec|slecet|selcet)\b', 'SELECT', current_sql, flags=re.I)
                err = "Syntax error: Typo in 'SELECT' keyword."
                detected_categories.append("syntax_error")
                if err not in errors_collected:
                    errors_collected.append(err)
                    tips_collected.append("> **Learning Tip:** The query keyword must be spelled `SELECT`.")

            # 1. Anti-patterns
            has_ap, ap_sql, ap_err, ap_tip = cls._check_anti_patterns(current_sql)
            if has_ap and ap_sql != current_sql:
                current_sql = ap_sql
                detected_categories.append("operator")
                if ap_err and ap_err not in errors_collected:
                    errors_collected.append(ap_err)
                if ap_tip and ap_tip not in tips_collected:
                    tips_collected.append(ap_tip)

            # 2. Missing projection: SELECT FROM <table>
            if re.search(r'\bSELECT\s+FROM\b', current_sql, re.I):
                current_sql = re.sub(r'\bSELECT\s+FROM\b', 'SELECT * FROM', current_sql, flags=re.I)
                err = "Syntax error near 'FROM': Missing column list or '*' after SELECT."
                detected_categories.append("syntax_error")
                if err not in errors_collected:
                    errors_collected.append(err)
                    tips_collected.append("> **Learning Tip:** A SQL `SELECT` statement requires specifying which columns to project (or `*` to select all columns) before `FROM`.")

            # 3. Missing FROM: SELECT * room
            for t in ALL_VALID_TABLES + list(TABLE_SYNONYMS.keys()):
                pattern_star = r'\bSELECT\s+\*\s+' + re.escape(t) + r'\b'
                if re.search(pattern_star, current_sql, re.I):
                    real_t = TABLE_SYNONYMS.get(t.lower(), t.lower())
                    current_sql = re.sub(pattern_star, f'SELECT * FROM {real_t}', current_sql, flags=re.I)
                    err = f"Syntax error near '{t}': Missing 'FROM' keyword between SELECT list and table name."
                    detected_categories.append("syntax_error")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append(f"> **Learning Tip:** The `FROM` keyword tells the SQL engine which table to retrieve rows from: `SELECT * FROM {real_t};`.")

                # Missing commas and FROM: SELECT col1 col2 table (e.g. SELECT room_id floor_number room)
                pattern_cols = r'\bSELECT\s+(?!\bFROM\b)([a-zA-Z0-9_]+)\s+(?!\bFROM\b)([a-zA-Z0-9_]+)\s+' + re.escape(t) + r'\b'
                col_match = re.search(pattern_cols, current_sql, re.I)
                if col_match:
                    c1, c2 = col_match.group(1), col_match.group(2)
                    real_t = TABLE_SYNONYMS.get(t.lower(), t.lower())
                    current_sql = f"SELECT {c1}, {c2} FROM {real_t}"
                    err = f"Syntax error: Missing commas between projected columns and missing 'FROM' keyword before table '{t}'."
                    detected_categories.append("syntax_error")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append(f"> **Learning Tip:** Multiple projected columns must be separated by commas: `SELECT {c1}, {c2} FROM {real_t};`.")

            # 4. Missing commas only: SELECT col1 col2 FROM table
            comma_match = re.search(r'\bSELECT\s+(?!\bFROM\b)([a-zA-Z0-9_]+)\s+(?!\bFROM\b)([a-zA-Z0-9_]+)\s+FROM\b', current_sql, re.I)
            if comma_match:
                c1, c2 = comma_match.group(1), comma_match.group(2)
                current_sql = re.sub(r'\bSELECT\s+' + c1 + r'\s+' + c2 + r'\s+FROM\b', f'SELECT {c1}, {c2} FROM', current_sql, flags=re.I)
                err = f"Syntax error: Missing comma between column '{c1}' and column '{c2}'."
                detected_categories.append("syntax_error")
                if err not in errors_collected:
                    errors_collected.append(err)

            # 5. Missing ON in JOIN: e.g. "SELECT * FROM attendee JOIN company;"
            if cls._is_missing_join_on(current_sql):
                join_match = re.search(r'\bFROM\s+([a-zA-Z0-9_]+)\s+(?:INNER\s+|LEFT\s+|RIGHT\s+)?JOIN\s+([a-zA-Z0-9_]+)', current_sql, re.I)
                if join_match:
                    t1 = TABLE_SYNONYMS.get(join_match.group(1).lower(), join_match.group(1).lower())
                    t2 = TABLE_SYNONYMS.get(join_match.group(2).lower(), join_match.group(2).lower())
                    fk_on = cls._get_fk_join_condition(t1, t2)
                    if fk_on:
                        current_sql = re.sub(r'\bFROM\s+[a-zA-Z0-9_]+\s+(?:INNER\s+|LEFT\s+|RIGHT\s+)?JOIN\s+[a-zA-Z0-9_]+', f'FROM {t1} JOIN {t2} ON {fk_on}', current_sql, flags=re.I)
                        err = f"Missing ON condition: An INNER JOIN between '{t1}' and '{t2}' requires an ON condition."
                        detected_categories.append("join_condition")
                        if err not in errors_collected:
                            errors_collected.append(err)
                            tips_collected.append(f"> **Why Foreign Keys Matter:** Without an `ON` condition, SQL creates an unintended Cartesian product (CROSS JOIN). Join condition: `ON {fk_on}`.")
                    else:
                        return cls._handle_ambiguous_join(raw_query, clean_query, t1, t2)

            # 6. Table name typos
            for syn, valid_t in TABLE_SYNONYMS.items():
                if re.search(r'\b' + re.escape(syn) + r'\b', current_sql, re.I):
                    current_sql = re.sub(r'\b' + re.escape(syn) + r'\b', valid_t, current_sql, flags=re.I)
                    err = f"The relation '{syn}' does not exist. Available table is '{valid_t}'."
                    detected_categories.append("table_typo")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append(f"> **Learning Tip:** The relation `{syn}` was not found. In this database, table names are singular: `{valid_t}`. Available tables: {', '.join(ALL_VALID_TABLES)}.")

            # 7. Check JOIN key mistakes
            if "presentation" in current_sql.lower() and "room" in current_sql.lower():
                if re.search(r'\b(?:presentation|p)\.room_id\s*=\s*(?:room|r)\.room_id\b', current_sql, re.I):
                    current_sql = re.sub(r'\b(?:presentation|p)\.room_id\s*=\s*(?:room|r)\.room_id\b', 'presentation.booked_room_id = room.room_id', current_sql, flags=re.I)
                    err = "presentation does not have a 'room_id' column; it uses foreign key 'booked_room_id' to reference room(room_id)."
                    detected_categories.append("join_condition")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append("> **Why Foreign Keys Matter:** In the schema, `presentation` stores room assignments under column `booked_room_id`. Joins must use `presentation.booked_room_id = room.room_id`.")

            if "company" in current_sql.lower() and "presentation" in current_sql.lower():
                if re.search(r'\b(?:presentation|p)\.company_id\s*=\s*(?:company|c)\.company_id\b', current_sql, re.I):
                    current_sql = re.sub(r'\b(?:presentation|p)\.company_id\s*=\s*(?:company|c)\.company_id\b', 'presentation.booked_company_id = company.company_id', current_sql, flags=re.I)
                    err = "presentation does not have a 'company_id' column; it uses foreign key 'booked_company_id' to reference company(company_id)."
                    detected_categories.append("join_condition")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append("> **Why Foreign Keys Matter:** In the schema, `presentation` stores sponsoring company IDs under column `booked_company_id`. Joins must use `presentation.booked_company_id = company.company_id`.")

            if "attendee" in current_sql.lower() and ("presentation_attendance" in current_sql.lower() or "attendance" in current_sql.lower()):
                if re.search(r'\bON\s+attendee_id\s*=\s*attendee_id\b', current_sql, re.I):
                    current_sql = re.sub(r'\bON\s+attendee_id\s*=\s*attendee_id\b', 'ON attendee.attendee_id = presentation_attendance.attendee_id', current_sql, flags=re.I)
                    err = "Ambiguous column reference: 'attendee_id' exists in both tables. You must qualify table names."
                    detected_categories.append("ambiguous")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append("> **Why Table Qualification Matters:** Qualify column names when joining tables with identical column names: `attendee.attendee_id = presentation_attendance.attendee_id`.")

            # Loop/Cycle check: if query was already seen and changed, break
            if current_sql.lower() in seen_queries and current_sql != prev_pass_sql:
                break
            seen_queries.add(current_sql.lower())

            # Try execution now
            res = TargetDatabaseManager.execute_query(current_sql)
            cols, rows, exec_time, db_err = res
            if db_err is None:
                # Successfully resolved!
                break

            # Handle execution errors: column typos, relation typos, constraint failures, missing group by, etc.
            # A) Relation / table error
            tbl_err_match = (
                re.search(r'no such table:\s*([a-zA-Z0-9_.]+)', db_err, re.I) or
                re.search(r'relation\s+"?([a-zA-Z0-9_.]+)"?\s+does not exist', db_err, re.I)
            )
            if tbl_err_match:
                wrong_t = tbl_err_match.group(1).lower().split('.')[-1]
                if wrong_t in TABLE_SYNONYMS:
                    real_t = TABLE_SYNONYMS[wrong_t]
                    current_sql = re.sub(r'\b' + re.escape(wrong_t) + r'\b', real_t, current_sql, flags=re.I)
                    err = f"The relation '{wrong_t}' does not exist. The available table is '{real_t}'."
                    detected_categories.append("table_typo")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append(f"> **Learning Tip:** In this database, table names are singular: `{real_t}`. Available tables: {', '.join(ALL_VALID_TABLES)}.")
                    continue

            # B) Column error or unquoted literal
            col_err_match = (
                re.search(r'no such column:\s*([a-zA-Z0-9_.]+)', db_err, re.I) or
                re.search(r'column\s+"?([a-zA-Z0-9_.]+)"?\s+does not exist', db_err, re.I)
            )
            if col_err_match:
                full_col = col_err_match.group(1)
                wrong_col = full_col.split('.')[-1]

                # Check if this wrong_col is an unquoted string in WHERE clause
                unquoted_match = re.search(r'=\s*(' + re.escape(wrong_col) + r')\b', current_sql, re.I)
                if unquoted_match and wrong_col.lower() not in ["null", "true", "false"]:
                    val = unquoted_match.group(1)
                    current_sql = re.sub(r'=\s*' + re.escape(val) + r'\b', f"= '{val}'", current_sql)
                    err = f"Column '{val}' does not exist. String literal '{val}' must be enclosed in single quotes ('{val}')."
                    detected_categories.append("syntax_error")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append(f"> **Learning Tip:** In SQL, string literals like `'{val}'` must be wrapped in single quotes. Without quotes, SQL treats `{val}` as a database column identifier.")
                    continue

                # Check column synonyms
                target_table = cls._detect_primary_table(current_sql)
                matched_col = None

                if target_table and target_table in SCHEMA_TABLES:
                    syns = SCHEMA_TABLES[target_table]["synonyms"]
                    if wrong_col.lower() in syns:
                        matched_col = syns[wrong_col.lower()]

                if not matched_col:
                    for t, info in SCHEMA_TABLES.items():
                        if wrong_col.lower() in info["synonyms"]:
                            matched_col = info["synonyms"][wrong_col.lower()]
                            target_table = t
                            break

                if matched_col:
                    if '.' in full_col:
                        prefix = full_col.split('.')[0]
                        current_sql = re.sub(r'\b' + re.escape(prefix) + r'\.' + re.escape(wrong_col) + r'\b', f"{prefix}.{matched_col}", current_sql, flags=re.I)
                    else:
                        current_sql = re.sub(r'\b' + re.escape(wrong_col) + r'\b', matched_col, current_sql, flags=re.I)

                    tbl_info = f" in table '{target_table}'" if target_table else ""
                    err = f"Column '{wrong_col}' does not exist{tbl_info}. Available column: '{matched_col}'."
                    detected_categories.append("column_typo")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append(f"> **Learning Tip:** The system identified `{matched_col}` as the closest valid column{tbl_info}. Database column names must match the schema exactly.")
                    continue

            # C) Ambiguous column reference
            ambig_err_match = (
                re.search(r'ambiguous column name:\s*([a-zA-Z0-9_.]+)', db_err, re.I) or
                re.search(r'column reference "([a-zA-Z0-9_.]+)" is ambiguous', db_err, re.I)
            )
            if ambig_err_match:
                ambig_col = ambig_err_match.group(1).lower()
                if "attendee_id" in ambig_col and "presentation_attendance" in current_sql.lower() and "attendee" in current_sql.lower():
                    current_sql = re.sub(r'\bON\s+attendee_id\s*=\s*attendee_id\b', 'ON attendee.attendee_id = presentation_attendance.attendee_id', current_sql, flags=re.I)
                    err = "Ambiguous column reference: 'attendee_id' exists in both tables. You must qualify table names."
                    detected_categories.append("ambiguous")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append("> **Why Table Qualification Matters:** When multiple joined tables share column names, qualify them with their table names: `attendee.attendee_id = presentation_attendance.attendee_id`.")
                    continue

            # D) Missing GROUP BY clause in PostgreSQL / standard SQL
            grp_err_match = re.search(r'must appear in the GROUP BY clause or be used in an aggregate function', db_err, re.I)
            if grp_err_match and "GROUP BY" not in current_sql.upper():
                sel_match = re.search(r'\bSELECT\s+([a-zA-Z0-9_.]+)\s*,\s*(?:COUNT|SUM|AVG|MIN|MAX)\b', current_sql, re.I)
                if sel_match:
                    col_to_grp = sel_match.group(1)
                    current_sql = f"{current_sql.rstrip(';')} GROUP BY {col_to_grp}"
                    err = f"Missing GROUP BY clause: In PostgreSQL, selecting column '{col_to_grp}' alongside an aggregate function requires 'GROUP BY {col_to_grp}'."
                    detected_categories.append("missing_group_by")
                    if err not in errors_collected:
                        errors_collected.append(err)
                        tips_collected.append(f"> **Learning Tip:** In standard SQL and PostgreSQL, any non-aggregated column in the SELECT list must be included in the GROUP BY clause: `GROUP BY {col_to_grp}`.")
                    continue

            # E) Division by zero
            if "division by zero" in db_err.lower():
                err = "Division by zero error: Mathematical division by zero is undefined in SQL."
                detected_categories.append("operator")
                errors_collected.append(err)
                tips_collected.append("> **Learning Tip:** Mathematical division by zero will cause runtime errors in PostgreSQL. Use `NULLIF(denominator, 0)` to handle zeros safely.")
                break

            # F) Constraint errors
            if "UNIQUE constraint failed" in db_err or "duplicate key value" in db_err.lower():
                err = f"Primary Key Violation: {db_err}. Primary key values must be unique across all rows in the table."
                detected_categories.append("syntax_error")
                errors_collected.append(err)
                tips_collected.append("> **Why Primary Keys Matter:** A Primary Key uniquely identifies each record. Inserting a duplicate ID violates entity integrity.")
                break

            if "CHECK constraint failed" in db_err or "violates check constraint" in db_err.lower():
                err = f"CHECK Constraint Violation: {db_err}. The inserted data violates business logic constraints (such as end_time > start_time)."
                detected_categories.append("syntax_error")
                errors_collected.append(err)
                tips_collected.append("> **Why Constraints Matter:** CHECK constraints prevent logically invalid data from entering the database.")
                break

            if "NOT NULL constraint failed" in db_err or "null value in column" in db_err.lower():
                err = f"NOT NULL Constraint Violation: {db_err}. A required column was omitted or given a NULL value."
                detected_categories.append("syntax_error")
                errors_collected.append(err)
                break

            # If no rule matched, break out to LLM fallback
            break

        # Check final execution of corrected query
        res = TargetDatabaseManager.execute_query(current_sql)
        cols, rows, exec_time, db_err = res
        if db_err is None and current_sql != clean_query:
            combined_err = " | ".join(errors_collected) if errors_collected else "Syntax / relation mismatch"
            combined_tip = "\n\n".join(tips_collected) if tips_collected else ""
            primary_cat = detected_categories[0] if detected_categories else "syntax_error"
            guard = "schema_unique" if primary_cat == "join_condition" else "safe_mechanical"
            return cls._execute_and_package(
                original_sql=raw_query,
                corrected_sql=current_sql,
                error_identified=combined_err,
                explanation=combined_tip,
                is_valid=False,
                error_category=primary_cat,
                semantic_guard=guard
            )

        # --- STEP 6: LLM Fallback for Any Unresolved or Complex SQL Errors ---
        llm_res = cls._llm_diagnose_and_correct(raw_query, db_err or "Unknown SQL error")
        if llm_res and llm_res.get("corrected_sql"):
            cand_sql = llm_res["corrected_sql"].strip().rstrip(';')
            cand_safe, _ = ASTSecurityGate.validate_sql(cand_sql)
            is_cand_cartesian = bool(re.search(r'\bON\s+(?:1\s*=\s*1|TRUE|1)\b', cand_sql, re.I))
            if cand_safe and not is_cand_cartesian:
                return cls._execute_and_package(
                    original_sql=raw_query,
                    corrected_sql=cand_sql,
                    error_identified=llm_res.get("error_identified", db_err),
                    explanation=llm_res.get("explanation", ""),
                    is_valid=False,
                    error_category="syntax_error",
                    semantic_guard="safe_mechanical"
                )

        # If completely unresolvable, return clean error report
        err_msg = " | ".join(errors_collected) if errors_collected else (db_err or "SQL Execution Error")
        tip_msg = "\n\n".join(tips_collected) if tips_collected else ""
        primary_cat = detected_categories[0] if detected_categories else "syntax_error"
        return {
            "request_type": "sql_diagnostic",
            "status": "error",
            "error_category": primary_cat,
            "semantic_guard": "safe_mechanical",
            "is_valid": False,
            "original_sql": raw_query,
            "corrected_sql": current_sql if current_sql != clean_query else None,
            "sql": None,
            "error_identified": err_msg,
            "learning_tip": tip_msg,
            "clause_breakdown": cls.generate_clause_breakdown(raw_query),
            "diff": cls.compute_sql_diff(raw_query, current_sql) if current_sql != clean_query else None,
            "clarification": None,
            "summary": f"SQL Execution Error: {err_msg}",
            "explanation": f"SQL Execution Error: {err_msg}\n\n{tip_msg}".strip(),
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": exec_time,
            "dialect": getattr(res, 'dialect', 'Database')
        }

    @classmethod
    def _is_missing_join_on(cls, sql: str) -> bool:
        """Determines if a query has an INNER/LEFT/RIGHT JOIN missing an ON or USING clause."""
        unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", '', sql)
        joins = len(re.findall(r'\b(?:INNER\s+|LEFT\s+|RIGHT\s+)?JOIN\b', unquoted, re.I)) - len(re.findall(r'\b(?:CROSS|NATURAL)\s+JOIN\b', unquoted, re.I))
        ons = len(re.findall(r'\bON\b', unquoted, re.I)) + len(re.findall(r'\bUSING\b', unquoted, re.I))
        return joins > ons

    @classmethod
    def _check_incomplete_clauses(cls, raw_query: str, clean_query: str) -> Optional[Dict[str, Any]]:
        """Detects incomplete SQL clauses and returns clarification requests."""
        # Check trailing WHERE, ORDER BY, GROUP BY, HAVING
        incomplete_match = re.search(r'\b(WHERE|ORDER\s+BY|GROUP\s+BY|HAVING)\s*;?$', clean_query, re.I)
        if incomplete_match:
            clause = incomplete_match.group(1).upper()
            if "WHERE" in clause:
                clarification_msg = "Incomplete query: The WHERE clause requires a condition (for example: WHERE floor_number = 2 or WHERE seat_capacity >= 40). What condition did you intend to filter by?"
                err_msg = "Incomplete WHERE clause: The WHERE keyword must be followed by a valid filtering condition."
            elif "ORDER" in clause:
                clarification_msg = "Incomplete query: The ORDER BY clause requires a column name to sort by (for example: ORDER BY seat_capacity DESC or ORDER BY room_id ASC). Which column did you intend to sort by?"
                err_msg = "Incomplete ORDER BY clause: The ORDER BY clause requires one or more column names."
            elif "GROUP" in clause:
                clarification_msg = "Incomplete query: The GROUP BY clause requires one or more columns to group by. Which column did you intend to group by?"
                err_msg = "Incomplete GROUP BY clause."
            else:
                clarification_msg = "Incomplete query: The HAVING clause requires an aggregate condition. What condition did you intend to specify?"
                err_msg = "Incomplete HAVING clause."

            explanation_text = f"Incomplete SQL clause: {err_msg} {clarification_msg}"
            return {
                "request_type": "clarification",
                "status": "clarification",
                "error_category": "incomplete_clause",
                "semantic_guard": "ambiguous_clarification",
                "is_valid": False,
                "original_sql": raw_query,
                "corrected_sql": None,
                "sql": None,
                "error_identified": err_msg,
                "learning_tip": "The query ended abruptly with an incomplete clause. Specify the missing filter or sorting condition to complete your query.",
                "clause_breakdown": cls.generate_clause_breakdown(clean_query),
                "diff": None,
                "clarification": clarification_msg,
                "summary": explanation_text,
                "explanation": explanation_text,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0.0,
                "dialect": "Database"
            }

        # Check trailing AND / OR in WHERE clause
        trailing_conj = re.search(r'\bWHERE\s+.*?\b(AND|OR)\s*;?$', clean_query, re.I)
        if trailing_conj:
            conj = trailing_conj.group(1).upper()
            clarification_msg = f"Incomplete query: The WHERE clause ends with an incomplete '{conj}' condition. What additional filter condition did you intend to apply?"
            err_msg = f"Incomplete boolean expression: The '{conj}' keyword must be followed by another condition."
            explanation_text = f"Incomplete SQL condition: {err_msg} {clarification_msg}"
            return {
                "request_type": "clarification",
                "status": "clarification",
                "error_category": "incomplete_clause",
                "semantic_guard": "ambiguous_clarification",
                "is_valid": False,
                "original_sql": raw_query,
                "corrected_sql": None,
                "sql": None,
                "error_identified": err_msg,
                "learning_tip": f"The '{conj}' conjunction connects multiple boolean conditions. You must provide a valid condition after '{conj}'.",
                "clause_breakdown": cls.generate_clause_breakdown(clean_query),
                "diff": None,
                "clarification": clarification_msg,
                "summary": explanation_text,
                "explanation": explanation_text,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0.0,
                "dialect": "Database"
            }

        return None

    @classmethod
    def _execute_and_package(
        cls,
        original_sql: str,
        corrected_sql: str,
        error_identified: str,
        explanation: str,
        is_valid: bool = False,
        error_category: str = "syntax_error",
        semantic_guard: str = "safe_mechanical"
    ) -> Dict[str, Any]:
        """Executes the corrected SQL query and packages the standardized diagnostic response."""
        sql_to_run = corrected_sql.rstrip(';')
        res = TargetDatabaseManager.execute_query(sql_to_run)
        cols, rows, exec_time, db_err = res
        dialect_used = getattr(res, 'dialect', 'Database')

        diff = cls.compute_sql_diff(original_sql, corrected_sql)
        clause_breakdown = cls.generate_clause_breakdown(corrected_sql)

        clean_exp = (explanation or "").strip()
        formatted_summary = (
            f"**Error Identified:** {error_identified}\n\n"
            f"{clean_exp}\n\n"
            f"Executed minimal correction on {dialect_used}. Retrieved {len(rows)} record(s)."
        )

        return {
            "request_type": "sql_diagnostic",
            "status": "corrected",
            "error_category": error_category,
            "semantic_guard": semantic_guard,
            "is_valid": is_valid,
            "original_sql": original_sql,
            "corrected_sql": corrected_sql,
            "sql": sql_to_run,
            "error_identified": error_identified,
            "learning_tip": clean_exp,
            "clause_breakdown": clause_breakdown,
            "diff": diff,
            "clarification": None,
            "summary": formatted_summary,
            "explanation": formatted_summary,
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": exec_time,
            "dialect": dialect_used
        }

    @classmethod
    def _check_destructive_dml(cls, sql: str) -> Optional[Dict[str, Any]]:
        """Provides pedagogical safety feedback on UPDATE/DELETE statements without WHERE clauses."""
        clean = sql.strip()
        dialect_used = TargetDatabaseManager.get_active_backend().capitalize()
        # DELETE without WHERE
        if re.search(r'^\s*DELETE\s+FROM\s+([a-zA-Z0-9_]+)\s*;?$', clean, re.I):
            tbl = re.search(r'^\s*DELETE\s+FROM\s+([a-zA-Z0-9_]+)', clean, re.I).group(1)
            real_t = TABLE_SYNONYMS.get(tbl.lower(), tbl.lower())
            err = f"Unscoped DELETE Statement: 'DELETE FROM {tbl};' does not include a WHERE clause, and data modification is disabled in this read-only sandbox."
            corrected = f"SELECT * FROM {real_t} WHERE {real_t}_id = 1;"
            tip = f"A DELETE statement without a WHERE clause deletes every single record in the '{real_t}' table. In this sandbox, database modifications are held in dry-run mode. To inspect matching rows, use: SELECT * FROM {real_t} WHERE {real_t}_id = 1."
            exp = f"{err} {tip}"
            return {
                "request_type": "sql_diagnostic",
                "status": "security_rejected",
                "error_category": "unscoped_dml",
                "semantic_guard": "security_rejected",
                "is_valid": False,
                "original_sql": sql,
                "corrected_sql": corrected,
                "sql": None,
                "error_identified": err,
                "learning_tip": tip,
                "clause_breakdown": cls.generate_clause_breakdown(corrected),
                "diff": cls.compute_sql_diff(sql, corrected),
                "clarification": None,
                "summary": exp,
                "explanation": exp,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0.0,
                "dialect": dialect_used
            }

        # UPDATE without WHERE
        if re.search(r'^\s*UPDATE\s+([a-zA-Z0-9_]+)\s+SET\s+[^;]+;?$', clean, re.I) and not re.search(r'\bWHERE\b', clean, re.I):
            tbl = re.search(r'^\s*UPDATE\s+([a-zA-Z0-9_]+)', clean, re.I).group(1)
            real_t = TABLE_SYNONYMS.get(tbl.lower(), tbl.lower())
            err = f"Unscoped UPDATE Statement: UPDATE without a WHERE clause will overwrite all records in table '{tbl}'."
            corrected = f"SELECT * FROM {real_t} WHERE {real_t}_id = 1;"
            tip = f"An UPDATE statement without a WHERE clause modifies every record in the '{real_t}' table. In this sandbox, database modifications are held in dry-run mode. To inspect rows, use: SELECT * FROM {real_t} WHERE {real_t}_id = 1."
            exp = f"{err} {tip}"
            return {
                "request_type": "sql_diagnostic",
                "status": "security_rejected",
                "error_category": "unscoped_dml",
                "semantic_guard": "security_rejected",
                "is_valid": False,
                "original_sql": sql,
                "corrected_sql": corrected,
                "sql": None,
                "error_identified": err,
                "learning_tip": tip,
                "clause_breakdown": cls.generate_clause_breakdown(corrected),
                "diff": cls.compute_sql_diff(sql, corrected),
                "clarification": None,
                "summary": exp,
                "explanation": exp,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0.0,
                "dialect": dialect_used
            }

        return None

    @classmethod
    def _handle_security_violation(cls, raw_query: str, clean_query: str, sec_msg: str) -> Dict[str, Any]:
        """
        Translates AST security rejections into pedagogical feedback.
        Distinguishes between multiple statements, destructive DDL, and educational DML statements.
        """
        import sqlparse
        dialect_used = TargetDatabaseManager.get_active_backend().capitalize()

        # 1. Multiple statements / Stacked queries
        parsed = sqlparse.parse(clean_query)
        uncommented = re.sub(r'--.*$', '', clean_query, flags=re.MULTILINE)
        uncommented = re.sub(r'/\*.*?\*/', ' ', uncommented, flags=re.DOTALL).strip()
        unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", "''", uncommented).rstrip('; \t\n')
        has_multiple = len(parsed) > 1 or ';' in unquoted

        if has_multiple:
            err = "Multiple statements detected: Stacked queries separated by semicolons are not permitted."
            tip = (
                "> **Security & Educational Policy:** Stacked queries (multiple statements in a single submission) "
                "are blocked to prevent SQL injection vulnerabilities and maintain clear execution feedback. "
                "Please submit one SQL statement at a time."
            )
            return {
                "request_type": "sql_diagnostic",
                "status": "security_rejected",
                "error_category": "multiple_statements",
                "semantic_guard": "security_rejected",
                "is_valid": False,
                "original_sql": raw_query,
                "corrected_sql": None,
                "sql": None,
                "error_identified": err,
                "learning_tip": tip,
                "clause_breakdown": cls.generate_clause_breakdown(clean_query),
                "diff": None,
                "clarification": None,
                "summary": "Security Guard Violation: Multiple statements blocked. Submit one query at a time.",
                "explanation": f"Security Policy Violation: {err}\n\n{tip}",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0.0,
                "dialect": dialect_used
            }

        # 2. DML Operations (DELETE, UPDATE, INSERT)
        if re.search(r'^\s*DELETE\b', clean_query, re.I):
            has_where = bool(re.search(r'\bWHERE\b', clean_query, re.I))
            tbl_match = re.search(r'^\s*DELETE\s+FROM\s+([a-zA-Z0-9_]+)', clean_query, re.I)
            tbl = tbl_match.group(1) if tbl_match else "table"
            real_t = TABLE_SYNONYMS.get(tbl.lower(), tbl.lower())

            if not has_where:
                err = f"Unscoped DELETE Statement: 'DELETE FROM {tbl};' lacks a WHERE clause, and data modification is disabled in this read-only sandbox."
                tip = (
                    f"> **Pedagogical Warning:** Running `DELETE FROM {real_t};` without a `WHERE` clause wipes every record from the table. "
                    f"Furthermore, in this learning environment, database writes are disabled to protect benchmark data. "
                    f"To safely preview records, run: `SELECT * FROM {real_t} WHERE {real_t}_id = 1;`."
                )
                suggested_sql = f"SELECT * FROM {real_t} WHERE {real_t}_id = 1;"
                cat = "unscoped_dml"
            else:
                where_clause = clean_query[re.search(r'\bWHERE\b', clean_query, re.I).start():]
                err = f"Data Modification Blocked: DELETE statements cannot be executed in this read-only learning environment."
                tip = (
                    f"> **Read-Only Sandbox Policy:** The database is mounted in read-only mode to preserve conference data for all exercises. "
                    f"You can verify your filter logic safely with an equivalent SELECT statement: `SELECT * FROM {real_t} {where_clause};`."
                )
                suggested_sql = f"SELECT * FROM {real_t} {where_clause};"
                cat = "scoped_dml"

            return {
                "request_type": "sql_diagnostic",
                "status": "security_rejected",
                "error_category": cat,
                "semantic_guard": "security_rejected",
                "is_valid": False,
                "original_sql": raw_query,
                "corrected_sql": suggested_sql,
                "sql": None,
                "error_identified": err,
                "learning_tip": tip,
                "clause_breakdown": cls.generate_clause_breakdown(clean_query),
                "diff": cls.compute_sql_diff(raw_query, suggested_sql),
                "clarification": None,
                "summary": f"Security Guard Violation: {err}",
                "explanation": f"Security Policy Violation: {err}\n\n{tip}",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0.0,
                "dialect": dialect_used
            }

        if re.search(r'^\s*UPDATE\b', clean_query, re.I):
            has_where = bool(re.search(r'\bWHERE\b', clean_query, re.I))
            tbl_match = re.search(r'^\s*UPDATE\s+([a-zA-Z0-9_]+)', clean_query, re.I)
            tbl = tbl_match.group(1) if tbl_match else "table"
            real_t = TABLE_SYNONYMS.get(tbl.lower(), tbl.lower())

            if not has_where:
                err = f"Unscoped UPDATE Statement: UPDATE without a WHERE clause will overwrite all records in table '{tbl}'."
                tip = (
                    f"> **Pedagogical Warning:** An UPDATE statement without a WHERE clause modifies every row in `{real_t}`. "
                    f"Furthermore, data modification is disabled in this read-only sandbox. "
                    f"To safely preview records, run: `SELECT * FROM {real_t} WHERE {real_t}_id = 1;`."
                )
                suggested_sql = f"SELECT * FROM {real_t} WHERE {real_t}_id = 1;"
                cat = "unscoped_dml"
            else:
                where_clause = clean_query[re.search(r'\bWHERE\b', clean_query, re.I).start():]
                err = f"Data Modification Blocked: UPDATE statements cannot be executed in this read-only learning environment."
                tip = (
                    f"> **Read-Only Sandbox Policy:** The database is mounted in read-only mode. "
                    f"To preview the records targeted by your update, run: `SELECT * FROM {real_t} {where_clause};`."
                )
                suggested_sql = f"SELECT * FROM {real_t} {where_clause};"
                cat = "scoped_dml"

            return {
                "request_type": "sql_diagnostic",
                "status": "security_rejected",
                "error_category": cat,
                "semantic_guard": "security_rejected",
                "is_valid": False,
                "original_sql": raw_query,
                "corrected_sql": suggested_sql,
                "sql": None,
                "error_identified": err,
                "learning_tip": tip,
                "clause_breakdown": cls.generate_clause_breakdown(clean_query),
                "diff": cls.compute_sql_diff(raw_query, suggested_sql),
                "clarification": None,
                "summary": f"Security Guard Violation: {err}",
                "explanation": f"Security Policy Violation: {err}\n\n{tip}",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0.0,
                "dialect": dialect_used
            }

        if re.search(r'^\s*INSERT\b', clean_query, re.I):
            err = "Data Modification Blocked: INSERT statements are disabled in this read-only learning environment."
            tip = "> **Read-Only Sandbox Policy:** Data insertion is restricted to prevent modifying benchmark learning records."
            return {
                "request_type": "sql_diagnostic",
                "status": "security_rejected",
                "error_category": "scoped_dml",
                "semantic_guard": "security_rejected",
                "is_valid": False,
                "original_sql": raw_query,
                "corrected_sql": None,
                "sql": None,
                "error_identified": err,
                "learning_tip": tip,
                "clause_breakdown": cls.generate_clause_breakdown(clean_query),
                "diff": None,
                "clarification": None,
                "summary": f"Security Guard Violation: {err}",
                "explanation": f"Security Policy Violation: {err}\n\n{tip}",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "execution_time_ms": 0.0,
                "dialect": dialect_used
            }

        # 3. Prohibited DDL or Administrative Operations (DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, PRAGMA, etc.)
        err = sec_msg
        tip = (
            "> **Read-Only Architecture:** Schema alterations and administrative operations are strictly blocked. "
            "All queries must be read-only SELECT or CTE queries against the conference management schema."
        )
        return {
            "request_type": "sql_diagnostic",
            "status": "security_rejected",
            "error_category": "prohibited_operation",
            "semantic_guard": "security_rejected",
            "is_valid": False,
            "original_sql": raw_query,
            "corrected_sql": None,
            "sql": None,
            "error_identified": err,
            "learning_tip": tip,
            "clause_breakdown": cls.generate_clause_breakdown(clean_query),
            "diff": None,
            "clarification": None,
            "summary": f"Security Guard Violation: {err}",
            "explanation": f"Security Policy Violation: {err}\n\n{tip}",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": 0.0,
            "dialect": dialect_used
        }

    @classmethod
    def _handle_ambiguous_join(cls, raw_query: str, clean_query: str, t1: str, t2: str) -> Dict[str, Any]:
        """Handles table pairs that lack a direct foreign key relationship."""
        pair = {t1, t2}
        if pair == {"presentation", "attendee"}:
            clarification_msg = (
                "Tables 'presentation' and 'attendee' are not directly linked by a foreign key. "
                "Did you intend to view attendees who attended presentations (via 'presentation_attendance'), "
                "or the company's primary contact for the presentation (via 'company')?"
            )
            err = f"Ambiguous Join: Tables '{t1}' and '{t2}' have no direct foreign key relationship."
            tip = (
                "> **Why Foreign Keys & Junction Tables Matter:** There is no direct link between `presentation` and `attendee`.\n"
                "In relational database design, many-to-many relationships are bridged using junction tables. "
                "To relate them:\n\n"
                "1. **By Attendance Records (Junction Table):**\n"
                "   `SELECT * FROM presentation JOIN presentation_attendance ON presentation.presentation_id = presentation_attendance.presentation_id JOIN attendee ON presentation_attendance.attendee_id = attendee.attendee_id;`\n\n"
                "2. **By Sponsoring Company Primary Contact:**\n"
                "   `SELECT * FROM presentation JOIN company ON presentation.booked_company_id = company.company_id JOIN attendee ON company.primary_contact_attendee_id = attendee.attendee_id;`"
            )
        elif pair == {"room", "company"}:
            clarification_msg = (
                "Tables 'room' and 'company' are not directly linked. "
                "Did you intend to relate rooms and companies through booked presentations ('presentation')?"
            )
            err = f"Ambiguous Join: Tables '{t1}' and '{t2}' have no direct foreign key relationship."
            tip = (
                "> **Why Foreign Keys Matter:** `room` and `company` do not reference each other directly. "
                "They are connected through `presentation`, which holds both `booked_room_id` and `booked_company_id`.\n"
                "To join them:\n"
                "`SELECT * FROM company JOIN presentation ON company.company_id = presentation.booked_company_id JOIN room ON presentation.booked_room_id = room.room_id;`"
            )
        elif pair == {"room", "attendee"}:
            clarification_msg = (
                "Tables 'room' and 'attendee' have no direct foreign key. "
                "Did you intend to find attendees who attended presentations in specific rooms?"
            )
            err = f"Ambiguous Join: Tables '{t1}' and '{t2}' have no direct foreign key relationship."
            tip = (
                "> **Why Foreign Keys Matter:** Attendees and rooms are connected via `presentation_attendance` and `presentation`.\n"
                "To join them:\n"
                "`SELECT * FROM attendee JOIN presentation_attendance ON attendee.attendee_id = presentation_attendance.attendee_id JOIN presentation ON presentation_attendance.presentation_id = presentation.presentation_id JOIN room ON presentation.booked_room_id = room.room_id;`"
            )
        else:
            clarification_msg = (
                f"Tables '{t1}' and '{t2}' have no direct foreign key relationship. "
                f"Please specify the intermediate table or join condition you intended to use."
            )
            err = f"Ambiguous Join: Tables '{t1}' and '{t2}' cannot be directly joined without an explicit relationship path."
            tip = f"> **Learning Tip:** Available tables in the conference schema are: {', '.join(ALL_VALID_TABLES)}. Joins must follow established foreign key paths."

        explanation_text = f"{err} {clarification_msg}"
        return {
            "request_type": "clarification",
            "status": "clarification",
            "error_category": "ambiguous_join",
            "semantic_guard": "ambiguous_clarification",
            "is_valid": False,
            "original_sql": raw_query,
            "corrected_sql": None,
            "sql": None,
            "error_identified": err,
            "learning_tip": tip,
            "clause_breakdown": cls.generate_clause_breakdown(clean_query),
            "diff": None,
            "clarification": clarification_msg,
            "summary": explanation_text,
            "explanation": f"{err}\n\n{tip}",
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": 0.0,
            "dialect": TargetDatabaseManager.get_active_backend().capitalize()
        }

    @classmethod
    def _check_anti_patterns(cls, sql: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """Checks for common beginner syntax anti-patterns like ==, =>, TOTAL(*), etc."""
        has_modified = False
        res_sql = sql
        error = None
        tip = None

        # 1. NULL checks (check != NULL / <> NULL before = NULL!)
        if re.search(r'(!=|<>)\s*NULL\b', res_sql, re.I):
            res_sql = re.sub(r'(!=|<>)\s*NULL\b', 'IS NOT NULL', res_sql, flags=re.I)
            error = "Using '!= NULL' is invalid in SQL. In SQL, NULL represents an unknown value. Use 'IS NOT NULL'."
            tip = "> **Learning Tip:** In SQL, always test non-nullability with `IS NOT NULL` rather than `!= NULL`."
            has_modified = True

        if re.search(r'=\s*NULL\b', res_sql, re.I):
            res_sql = re.sub(r'=\s*NULL\b', 'IS NULL', res_sql, flags=re.I)
            error = "Using '= NULL' is invalid in SQL. In SQL, NULL represents an unknown value. Any equality check '= NULL' evaluates to UNKNOWN. Use 'IS NULL'."
            tip = "> **Learning Tip:** In SQL, NULL cannot be compared using `=`. Always use `IS NULL` or `IS NOT NULL`."
            has_modified = True

        # 2. Double equals (==)
        if "==" in res_sql:
            res_sql = res_sql.replace("==", "=")
            error = "In standard SQL, equality comparison uses a single '=' operator rather than '=='."
            tip = "> **Learning Tip:** Programming languages like Python, C, and JavaScript use `==` for comparison, but standard SQL uses `=`. Always use `=` in SQL `WHERE` clauses."
            has_modified = True

        # 3. Invalid comparison operator =>
        if "=>" in res_sql:
            res_sql = res_sql.replace("=>", ">=")
            error = "Syntax error: '=>' is invalid in SQL. Use '>=' for 'greater than or equal to'."
            tip = "> **Learning Tip:** In SQL, the greater-than or less-than sign always comes first in compound comparison operators (`>=`, `<=`, `<>`)."
            has_modified = True

        # 4. Invalid comparison operator =<
        if "=<" in res_sql:
            res_sql = res_sql.replace("=<", "<=")
            error = "Syntax error: '=<' is invalid in SQL. Use '<=' for 'less than or equal to'."
            tip = "> **Learning Tip:** In SQL, the less-than sign comes first: use `<=` instead of `=<`."
            has_modified = True

        # 5. TOTAL(*) aggregate
        if re.search(r'\bTOTAL\s*\(\s*\*\s*\)', res_sql, re.I):
            res_sql = re.sub(r'\bTOTAL\s*\(\s*\*\s*\)', 'COUNT(*)', res_sql, flags=re.I)
            error = "TOTAL(*) is not valid standard SQL for counting rows. Use the standard aggregate function COUNT(*)."
            tip = "> **Learning Tip:** `COUNT(*)` counts rows. In SQLite, `total(x)` sums numeric column values with floating-point semantics, but it requires a column expression and cannot take `*`."
            has_modified = True

        # 6. Negative LIMIT
        if re.search(r'\bLIMIT\s+-\d+', res_sql, re.I):
            res_sql = re.sub(r'\bLIMIT\s+-(\d+)', r'LIMIT \1', res_sql, flags=re.I)
            error = "Invalid LIMIT value: SQL LIMIT cannot be negative."
            tip = "> **Learning Tip:** The `LIMIT` clause specifies the maximum number of rows to return and must be a non-negative integer."
            has_modified = True

        # 7. HAVING without aggregate (used where WHERE should be)
        having_no_agg = re.search(r'\bHAVING\s+([a-zA-Z0-9_]+)\s*(=|<|>|<=|>=|!=)\s*([^\s;]+)', res_sql, re.I)
        if having_no_agg and "GROUP BY" not in res_sql.upper() and "COUNT(" not in res_sql.upper() and "SUM(" not in res_sql.upper() and "AVG(" not in res_sql.upper():
            res_sql = re.sub(r'\bHAVING\b', 'WHERE', res_sql, flags=re.I)
            error = "Using HAVING without GROUP BY or aggregate functions: HAVING filters groups after grouping, whereas WHERE filters individual rows."
            tip = "> **Learning Tip:** Use `WHERE` to filter individual rows before grouping. Use `HAVING` only to filter aggregated results produced by `GROUP BY`."
            has_modified = True

        # 8. GROUP BY missing non-aggregated projected column
        # e.g., "SELECT name, COUNT(*) FROM company;"
        missing_grp = re.search(r'\bSELECT\s+([a-zA-Z0-9_]+)\s*,\s*(COUNT|SUM|AVG|MIN|MAX)\([^)]+\)\s+FROM\s+([a-zA-Z0-9_]+)(?!\s+GROUP\s+BY)\b', res_sql, re.I)
        if missing_grp and "GROUP BY" not in res_sql.upper():
            col_name = missing_grp.group(1)
            res_sql = f"{res_sql.rstrip(';')} GROUP BY {col_name}"
            error = f"Missing GROUP BY clause: In standard SQL and PostgreSQL, selecting column '{col_name}' alongside an aggregate function requires 'GROUP BY {col_name}'."
            tip = f"> **Learning Tip:** In standard SQL, whenever you select both a regular column and an aggregate function (like `COUNT(*)`), you must group by the regular column: `GROUP BY {col_name}`."
            has_modified = True

        # 9. Multi-row scalar subquery = (SELECT ...) -> IN (SELECT ...)
        scalar_subq = re.search(r'=\s*\(\s*SELECT\b(?!.*LIMIT\s+1\b)', res_sql, re.I | re.DOTALL)
        if scalar_subq:
            res_sql = re.sub(r'=\s*(\(\s*SELECT\b)', r'IN \1', res_sql, flags=re.I)
            error = "Scalar subquery returning multiple rows: The '=' comparison expects exactly one value. Use 'IN' to test membership in a subquery result set."
            tip = "> **Why Subquery Operators Matter:** Use `=` only when a subquery is guaranteed to return a single row (e.g. using `LIMIT 1` or an aggregate function). Otherwise, use `IN`."
            has_modified = True

        # 10. Dialect date functions (only translate if active backend is SQLite)
        backend = TargetDatabaseManager.get_active_backend()
        if backend == 'sqlite':
            if re.search(r'\bCURDATE\(\)', res_sql, re.I):
                res_sql = re.sub(r'\bCURDATE\(\)', "DATE('now')", res_sql, flags=re.I)
                error = "MySQL function CURDATE() used. In SQLite fallback dialect, use DATE('now')."
                tip = "> **Learning Tip:** MySQL uses `CURDATE()`, PostgreSQL uses `CURRENT_DATE`, and SQLite uses `DATE('now')`."
                has_modified = True

            if re.search(r'\bNOW\(\)', res_sql, re.I):
                res_sql = re.sub(r'\bNOW\(\)', "DATETIME('now')", res_sql, flags=re.I)
                error = "PostgreSQL function NOW() used. When executing against SQLite fallback, use DATETIME('now')."
                tip = "> **Learning Tip:** In PostgreSQL, `NOW()` returns the current timestamp. In SQLite fallback, `DATETIME('now')` is used."
                has_modified = True

        return has_modified, res_sql, error, tip

    @classmethod
    def _get_fk_join_condition(cls, t1: str, t2: str) -> Optional[str]:
        """Finds foreign key relationship between two tables."""
        pair = {t1, t2}
        if pair == {"attendee", "company"}:
            return "company.primary_contact_attendee_id = attendee.attendee_id"
        if pair == {"presentation", "room"}:
            return "presentation.booked_room_id = room.room_id"
        if pair == {"company", "presentation"}:
            return "presentation.booked_company_id = company.company_id"
        if pair == {"attendee", "presentation_attendance"}:
            return "attendee.attendee_id = presentation_attendance.attendee_id"
        if pair == {"presentation", "presentation_attendance"}:
            return "presentation.presentation_id = presentation_attendance.presentation_id"
        return None

    @classmethod
    def _check_join_shorthand(cls, query: str) -> Optional[Dict[str, str]]:
        """Handles natural language JOIN shorthand queries submitted by learners."""
        clean = query.strip()
        lower = clean.lower()

        # Attendee with company
        if "attendee" in lower and "company" in lower and ("attendee.id" in lower or "attendee_id" in lower or "using" in lower):
            corrected = "SELECT * FROM attendee JOIN company ON company.primary_contact_attendee_id = attendee.attendee_id;"
            err = "Table 'attendee' uses primary key 'attendee_id' (not 'id'), and links to 'company' through foreign key 'company.primary_contact_attendee_id = attendee.attendee_id'."
            tip = "> **Why Foreign Keys Matter:** In this schema, `company` has a nullable foreign key `primary_contact_attendee_id` referencing `attendee(attendee_id)`. Joining them requires `ON company.primary_contact_attendee_id = attendee.attendee_id`."
            return {"corrected_sql": corrected, "error_identified": err, "explanation": tip}

        # Presentation with room
        if "presentation" in lower and "room" in lower and ("room_id" in lower or "alone" in lower or "using" in lower):
            corrected = "SELECT * FROM presentation JOIN room ON presentation.booked_room_id = room.room_id;"
            err = "Table 'presentation' does not have a 'room_id' column. It references 'room' via foreign key 'booked_room_id'. The join condition must be 'presentation.booked_room_id = room.room_id'."
            tip = "> **Why Foreign Keys Matter:** `presentation` uses the descriptive foreign key `booked_room_id` to refer to `room.room_id`. Joins must match foreign key names accurately."
            return {"corrected_sql": corrected, "error_identified": err, "explanation": tip}

        # Company with presentation
        if "company" in lower and "presentation" in lower and ("company_id" in lower or "alone" in lower or "using" in lower):
            corrected = "SELECT * FROM company JOIN presentation ON presentation.booked_company_id = company.company_id;"
            err = "Table 'presentation' does not have a 'company_id' column. It references 'company' via foreign key 'booked_company_id'. The join condition must be 'presentation.booked_company_id = company.company_id'."
            tip = "> **Why Foreign Keys Matter:** `presentation` uses foreign key `booked_company_id` to refer to `company.company_id`."
            return {"corrected_sql": corrected, "error_identified": err, "explanation": tip}

        # Attendee with presentation_attendance
        if "attendee" in lower and ("attendance" in lower or "presentation_attendance" in lower) and ("attendee_id" in lower or "alone" in lower or "using" in lower):
            corrected = "SELECT * FROM attendee JOIN presentation_attendance ON attendee.attendee_id = presentation_attendance.attendee_id;"
            err = "Ambiguous join key: Both 'attendee' and 'presentation_attendance' contain 'attendee_id'. Join conditions must qualify the table name: 'attendee.attendee_id = presentation_attendance.attendee_id'."
            tip = "> **Why Table Qualification Matters:** When both tables share a column name, SQL requires qualifying them with their table names to avoid ambiguity."
            return {"corrected_sql": corrected, "error_identified": err, "explanation": tip}

        return None

    @classmethod
    def _detect_primary_table(cls, sql: str) -> Optional[str]:
        """Detects the primary table referenced in the FROM clause."""
        match = re.search(r'\bFROM\s+([a-zA-Z0-9_]+)', sql, re.I)
        if match:
            t = match.group(1).lower()
            return TABLE_SYNONYMS.get(t, t)
        return None

    @classmethod
    def _llm_diagnose_and_correct(cls, query: str, db_error: str) -> Optional[Dict[str, Any]]:
        """Invokes LLM with strict minimal correction instructions if rule-based engine cannot resolve."""
        if not config.GROQ_API_KEY:
            return None

        try:
            from rag_engine import RAGEngine
            prompt_sys = (
                "You are an expert SQL Educational Mentor for beginners.\n"
                "A learner submitted a SQL query that failed with a database error.\n"
                "CRITICAL RULES:\n"
                "1. Make the SMALLEST POSSIBLE correction to the learner's original query. Do NOT invent a brand new query.\n"
                "2. If the query is incomplete (e.g. trailing WHERE, ORDER BY, GROUP BY), do NOT invent conditions. Request clarification.\n"
                "3. Database schema:\n"
                "   - attendee (attendee_id, first_name, last_name, phone, email, vip)\n"
                "   - room (room_id, floor_number, seat_capacity)\n"
                "   - company (company_id, name, description, primary_contact_attendee_id)\n"
                "   - presentation (presentation_id, booked_company_id, booked_room_id, start_time, end_time)\n"
                "   - presentation_attendance (ticket_id, presentation_id, attendee_id)\n"
                "4. Output strictly valid JSON matching this schema:\n"
                "{\n"
                '  "error_identified": "<clear error explanation>",\n'
                '  "corrected_sql": "<minimally corrected SQL or null if clarification needed>",\n'
                '  "explanation": "<detailed pedagogical explanation for learners>"\n'
                "}"
            )
            prompt_user = f"Learner SQL Query:\n{query}\n\nDatabase Error:\n{db_error}\n\nProvide the minimal correction and explanation JSON."
            response = RAGEngine.call_llm_with_circuit_breaker(prompt_sys, prompt_user, temperature=0.1)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except Exception as e:
            print(f"[SQLLearnerEngine LLM Error] {e}")
        return None
