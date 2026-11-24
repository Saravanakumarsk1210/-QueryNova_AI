import pytest
import os
import sys

# Ensure root path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import TargetDatabaseManager, QueryResult

def test_database_manager_backend_active():
    backend = TargetDatabaseManager.get_active_backend()
    assert backend in ["postgres", "sqlite"], f"Invalid backend: {backend}"

def test_execute_query_room_table():
    res = TargetDatabaseManager.execute_query("SELECT * FROM room;")
    cols, rows, exec_time, db_err = res
    assert db_err is None, f"Query execution failed: {db_err}"
    assert "room_id" in cols
    assert "seat_capacity" in cols
    assert len(rows) > 0, "No room records returned"
    assert hasattr(res, 'dialect')
    assert "rdbms_record" in res.dialect or "redbms_data.db" in res.dialect or "neon" in res.dialect.lower()

def test_execute_query_sqlite_fallback():
    res = TargetDatabaseManager.execute_query("SELECT * FROM room;", force_backend="sqlite")
    cols, rows, exec_time, db_err = res
    assert db_err is None, f"SQLite execution failed: {db_err}"
    assert "room_id" in cols
    assert len(rows) == 20, f"Expected 20 rooms in SQLite, got {len(rows)}"
    assert "SQLite" in res.dialect

def test_execute_query_read_only_enforcement():
    # Attempting to execute DML against target database
    res = TargetDatabaseManager.execute_query("UPDATE room SET seat_capacity = 999 WHERE room_id = 101;")
    cols, rows, exec_time, db_err = res
    assert db_err is not None, "DML statement should have failed in read-only mode"

