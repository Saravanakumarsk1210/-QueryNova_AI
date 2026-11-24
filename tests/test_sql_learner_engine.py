import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sql_learner_engine import SQLLearnerEngine

# Table name mistakes
@pytest.mark.parametrize("query, expected_table", [
    ("SELECT * FROM rooms;", "room"),
    ("SELECT * FROM attendees;", "attendee"),
    ("SELECT * FROM companies;", "company"),
    ("SELECT * FROM presentations;", "presentation"),
    ("SELECT * FROM attendance;", "presentation_attendance"),
])
def test_table_name_mistakes(query, expected_table):
    res = SQLLearnerEngine.diagnose_and_execute(query)
    assert res["status"] == "corrected"
    assert f"from {expected_table}" in res["corrected_sql"].lower()

# Column name mistakes
@pytest.mark.parametrize("query, expected_col", [
    ("SELECT id FROM room;", "room_id"),
    ("SELECT capacity FROM room;", "seat_capacity"),
    ("SELECT firstname FROM attendee;", "first_name"),
    ("SELECT lastname FROM attendee;", "last_name"),
    ("SELECT mobile FROM attendee;", "phone"),
    ("SELECT company_name FROM company;", "name"),
    ("SELECT startdate FROM presentation;", "start_time"),
])
def test_column_name_mistakes(query, expected_col):
    res = SQLLearnerEngine.diagnose_and_execute(query)
    assert res["status"] == "corrected"
    assert expected_col in res["corrected_sql"].lower()

# Syntax mistakes
def test_missing_star_in_select_from():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT FROM room;")
    assert res["status"] == "corrected"
    assert "select * from room" in res["corrected_sql"].lower()

def test_missing_from_keyword():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * room;")
    assert res["status"] == "corrected"
    assert "select * from room" in res["corrected_sql"].lower()

def test_missing_commas_and_from():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT room_id floor_number room;")
    assert res["status"] == "corrected"
    assert "room_id, floor_number from room" in res["corrected_sql"].lower()

# Incomplete clauses
def test_incomplete_where_clause():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM room WHERE;")
    assert res["status"] == "clarification"
    assert "clarification" in res
    assert "where" in res["clarification"].lower()

def test_incomplete_order_by_clause():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM room ORDER BY;")
    assert res["status"] == "clarification"
    assert "clarification" in res
    assert "order by" in res["clarification"].lower()

# Operators & quoting
def test_double_equals_operator():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM room WHERE seat_capacity == 40;")
    assert res["status"] == "corrected"
    assert "seat_capacity = 40" in res["corrected_sql"].lower()
    assert "==" not in res["corrected_sql"]

def test_reversed_comparison_operator():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM room WHERE seat_capacity => 50;")
    assert res["status"] == "corrected"
    assert "seat_capacity >= 50" in res["corrected_sql"].lower()

def test_unquoted_string_literal():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM attendee WHERE first_name = John;")
    assert res["status"] == "corrected"
    assert "first_name = 'john'" in res["corrected_sql"].lower()

# Aggregates
def test_total_star_to_count():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT TOTAL(*) FROM attendee;")
    assert res["status"] == "corrected"
    assert "count(*)" in res["corrected_sql"].lower()

# Valid queries (including zero-row query)
def test_valid_query_execution():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM room WHERE floor_number = 1;")
    assert res["status"] == "valid"
    assert res["is_valid"] is True
    assert len(res["rows"]) > 0

def test_valid_zero_row_query():
    res = SQLLearnerEngine.diagnose_and_execute("SELECT * FROM room WHERE floor_number = 9999;")
    assert res["status"] == "valid"
    assert res["is_valid"] is True
    assert len(res["rows"]) == 0
    assert "zero rows" in res["explanation"].lower()

