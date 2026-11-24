import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ast_security import ASTSecurityGate

def test_ast_valid_select():
    valid, msg = ASTSecurityGate.validate_sql("SELECT * FROM room WHERE room_id = 101;")
    assert valid is True
    assert "passed" in msg.lower()

def test_ast_valid_cte():
    valid, msg = ASTSecurityGate.validate_sql("WITH room_summary AS (SELECT * FROM room) SELECT * FROM room_summary;")
    assert valid is True

def test_ast_reject_drop():
    valid, msg = ASTSecurityGate.validate_sql("DROP TABLE room;")
    assert valid is False
    assert "prohibited" in msg.lower() or "drop" in msg.lower()

def test_ast_reject_delete():
    valid, msg = ASTSecurityGate.validate_sql("DELETE FROM attendee WHERE attendee_id = 1;")
    assert valid is False

def test_ast_reject_insert():
    valid, msg = ASTSecurityGate.validate_sql("INSERT INTO room VALUES (999, 1, 50);")
    assert valid is False

def test_ast_reject_update():
    valid, msg = ASTSecurityGate.validate_sql("UPDATE attendee SET first_name = 'Hacked';")
    assert valid is False

def test_ast_reject_pragma():
    valid, msg = ASTSecurityGate.validate_sql("PRAGMA table_info(room);")
    assert valid is False

def test_ast_reject_stacked_queries():
    valid, msg = ASTSecurityGate.validate_sql("SELECT * FROM room; SELECT * FROM attendee;")
    assert valid is False
    assert "multiple statements" in msg.lower() or "statements" in msg.lower()

def test_ast_reject_comment_obfuscation():
    valid, msg = ASTSecurityGate.validate_sql("/* malicious */ DROP TABLE room;")
    assert valid is False

