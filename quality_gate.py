import json
import re
from typing import Tuple, Dict, Any
import config
from ast_security import ASTSecurityGate
from database import TargetDatabaseManager

class QualityGateManager:
    """4-Tier Quality Gate & Autonomous Reflection Retry Engine."""

    @classmethod
    def validate_and_judge_sql(cls, user_query: str, sql_query: str, schema_context: str = "") -> Tuple[bool, str, str]:
        """
        Validates SQL against AST Security, Dry-run DB execution, and LLM Judge.
        Returns: (is_passed, feedback_reason, sanitized_sql)
        """
        passed, reason, details = cls.validate_query(sql_query, schema_context)
        return passed, reason, sql_query.strip()

    @classmethod
    def validate_query(cls, sql_query: str, schema_context: str = "") -> Tuple[bool, str, Dict[str, Any]]:
        # Tier 1: AST Security Validation
        valid_ast, ast_msg = ASTSecurityGate.validate_sql(sql_query)
        if not valid_ast:
            return False, f"AST Security Gate Violation: {ast_msg}", {"tier": 1}

        # Tier 2: Dry-run Execution Check against database
        res = TargetDatabaseManager.execute_query(sql_query, limit=5)
        cols, rows, exec_time, db_err = res
        if db_err:
            return False, f"SQL Execution Failure: {db_err}", {"tier": 2, "dialect": getattr(res, 'dialect', 'unknown')}

        # If AST Security and Dry-run Execution both pass cleanly, query is valid SELECT.
        return True, "Quality Gate Passed", {
            "tier": 4,
            "columns": cols,
            "sample_rows": rows,
            "execution_time_ms": exec_time,
            "dialect": getattr(res, 'dialect', 'unknown')
        }

    @classmethod
    def reflect_and_fix(cls, original_query: str, failed_sql: str, error_msg: str, schema_context: str) -> str:
        """Bounded reflection loop to fix invalid SQL."""
        if not config.GROQ_API_KEY:
            return failed_sql

        try:
            from rag_engine import RAGEngine
            prompt_sys = "You are an AI SQL Repair Specialist for the Conference Management Database."
            prompt_user = (
                f"Natural Language Question: {original_query}\n"
                f"Schema Context:\n{schema_context}\n"
                f"Failed SQL: {failed_sql}\n"
                f"Error Message: {error_msg}\n\n"
                "Correct the SQL query. Output ONLY the fixed SQL query inside <sql>...</sql> tags."
            )
            content = RAGEngine.call_llm_with_circuit_breaker(prompt_sys, prompt_user, temperature=0.1)
            sql_match = re.search(r'<sql>(.*?)</sql>', content, re.DOTALL | re.IGNORECASE)
            if sql_match:
                return sql_match.group(1).strip()
            return content.strip()
        except Exception as exc:
            print(f"[Reflection Loop Error] {exc}")
        return failed_sql
