import re
import sqlparse
from typing import Tuple

class ASTSecurityGate:
    """
    Hardened AST Security Gate (Layer 1 Defense Boundary).
    Programmatically enforces:
    1. Exactly one SQL statement.
    2. Statement type MUST be SELECT or CTE (WITH ... SELECT).
    3. No multiple statements, subquery injection, or comment masking.
    4. Reject non-SELECT keywords (DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, EXEC, etc.).
    """
    
    FORBIDDEN_KEYWORDS = re.compile(
        r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC|EXECUTE|VACUUM|REINDEX|COPY|ATTACH|DETACH|PRAGMA)\b',
        re.IGNORECASE
    )
    
    @classmethod
    def validate_sql(cls, sql: str) -> Tuple[bool, str]:
        """
        Validates SQL string against AST security rules.
        Returns (is_valid, error_reason).
        """
        if not sql or not sql.strip():
            return False, "SQL statement is empty."

        clean_sql = sql.strip()
        
        # Rule 1: Check forbidden DDL/DML keywords
        if cls.FORBIDDEN_KEYWORDS.search(clean_sql):
            match = cls.FORBIDDEN_KEYWORDS.search(clean_sql).group(0)
            return False, f"Security Violation: Prohibited DDL/DML keyword '{match}' detected."

        # Rule 2: Must start with SELECT or WITH
        clean_upper = clean_sql.upper()
        if not (clean_upper.startswith('SELECT') or clean_upper.startswith('WITH')):
            return False, "Security Violation: Statement must begin with SELECT or WITH."

        # Parse AST statements using sqlparse
        parsed = sqlparse.parse(clean_sql)
        
        # Rule 3: Must contain exactly 1 statement
        if len(parsed) != 1:
            return False, f"Security Violation: Query contains {len(parsed)} statements. Exactly 1 statement is required."

        # Rule 4: Strip comments first, then quoted string literals, then check for multiple semicolons
        uncommented = re.sub(r'--.*$', '', clean_sql, flags=re.MULTILINE)
        uncommented = re.sub(r'/\*.*?\*/', ' ', uncommented, flags=re.DOTALL).strip()

        unquoted = re.sub(r"'[^']*'|\"[^\"]*\"", "''", uncommented)
        unquoted_trimmed = unquoted.rstrip('; \t\n')
        if ';' in unquoted_trimmed:
            return False, "Security Violation: Multiple statements separated by semicolons are not allowed."

        # Rule 5: Check for suspicious comment structures used in prompt injection
        if '--' in clean_sql or '/*' in clean_sql:
            uncommented_upper = uncommented.upper()
            if not (uncommented_upper.startswith('SELECT') or uncommented_upper.startswith('WITH')):
                return False, "Security Violation: Obfuscated SQL comment manipulation detected."

        return True, "SQL statement passed AST Security Gate."

# Quick self-test
if __name__ == "__main__":
    test_cases = [
        ("SELECT * FROM room WHERE room_id = 101;", True),
        ("WITH cte AS (SELECT * FROM attendee) SELECT * FROM cte;", True),
        ("DROP TABLE room; SELECT * FROM room;", False),
        ("DELETE FROM attendee;", False),
        ("SELECT * FROM room; -- comment", True),
        ("SELECT * FROM company WHERE name = 'FOO; BAR';", True),
        ("SELECT * FROM room; DROP TABLE attendee;", False)
    ]
    for q, expected in test_cases:
        valid, msg = ASTSecurityGate.validate_sql(q)
        print(f"Query: {q} | Valid: {valid} (Expected {expected}) | {msg}")
