import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sql_learner_engine import SQLLearnerEngine
from database import TargetDatabaseManager

def test_postgresql_ilike_feature():
    q = "SELECT * FROM attendee WHERE first_name ILIKE 'j%';"
    res = SQLLearnerEngine.diagnose_and_execute(q)
    assert res["status"] == "valid"
    assert res["is_valid"] is True
    assert len(res["rows"]) > 0

def test_postgresql_date_trunc_feature():
    q = "SELECT DATE_TRUNC('month', start_time) AS presentation_month, COUNT(*) AS count FROM presentation GROUP BY DATE_TRUNC('month', start_time);"
    res = SQLLearnerEngine.diagnose_and_execute(q)
    assert res["status"] == "valid"
    assert res["is_valid"] is True
    assert len(res["rows"]) > 0
    assert "presentation_month" in res["columns"]

def test_postgresql_cte_feature():
    q = """
    WITH attendee_attendance AS (
        SELECT attendee_id, COUNT(*) AS total_attended
        FROM presentation_attendance
        GROUP BY attendee_id
    )
    SELECT * FROM attendee_attendance WHERE total_attended >= 1;
    """
    res = SQLLearnerEngine.diagnose_and_execute(q)
    assert res["status"] == "valid"
    assert res["is_valid"] is True
    assert len(res["rows"]) > 0

def test_postgresql_window_function():
    q = "SELECT room_id, seat_capacity, RANK() OVER (ORDER BY seat_capacity DESC) as cap_rank FROM room;"
    res = SQLLearnerEngine.diagnose_and_execute(q)
    assert res["status"] == "valid"
    assert res["is_valid"] is True
    assert "cap_rank" in res["columns"]

def test_postgresql_string_number_comparison():
    q = "SELECT * FROM room WHERE room_id = '101';"
    res = SQLLearnerEngine.diagnose_and_execute(q)
    assert res["status"] == "valid"
    assert res["is_valid"] is True
    assert len(res["rows"]) == 1

