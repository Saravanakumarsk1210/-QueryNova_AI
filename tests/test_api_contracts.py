import pytest
import os
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from server import app

client = TestClient(app)

def test_api_me_clean_profile():
    res = client.get("/api/me")
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is True
    assert "doctor@aravind.org" not in str(data)
    assert data["user"]["email"] == "learner@querynova.local"
    assert data["user"]["role"] == "learner"

def test_api_execute_sql_valid():
    payload = {"sql": "SELECT room_id, seat_capacity FROM room ORDER BY room_id LIMIT 2;"}
    res = client.post("/api/execute-sql", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert len(data["rows"]) == 2
    assert "room_id" in data["columns"]
    assert "dialect" in data
    assert "rdbms_record" in data["dialect"] or "redbms_data" in data["dialect"] or "neon" in data["dialect"].lower()

def test_api_execute_sql_security_block():
    payload = {"sql": "DROP TABLE room;"}
    res = client.post("/api/execute-sql", json=payload)
    assert res.status_code == 400
    assert "prohibited" in res.json()["detail"].lower() or "security" in res.json()["detail"].lower()

def test_api_execute_sql_multiple_statements_block():
    payload = {"sql": "SELECT * FROM room; SELECT * FROM attendee;"}
    res = client.post("/api/execute-sql", json=payload)
    assert res.status_code == 400
    detail = res.json()["detail"].lower()
    assert "statement" in detail and ("1 statement is required" in detail or "multiple statements" in detail)

def test_api_chats_list():
    res = client.get("/api/chats")
    assert res.status_code == 200
    assert "chats" in res.json()
