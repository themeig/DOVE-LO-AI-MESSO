import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

def setup_module():
    init_db()

def test_simulator_users_list():
    res = client.get("/api/simulator/users")
    assert res.status_code == 200
    data = res.json()
    assert "users" in data
    assert len(data["users"]) >= 3
    emails = [u["email"] for u in data["users"]]
    assert "marco.rossi@test.it" in emails
    assert "laura.bianchi@test.it" in emails

def test_simulator_switch_user():
    res = client.post("/api/simulator/switch-user", json={"user_key": "laura"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "laura.bianchi@test.it"
    assert data["user"]["full_name"] == "Laura Bianchi"

def test_simulator_switch_user_by_email():
    res = client.post("/api/simulator/switch-user", json={"email": "marco.rossi@test.it"})
    assert res.status_code == 200
    data = res.json()
    assert data["user"]["email"] == "marco.rossi@test.it"
    assert "access_token" in data

def test_simulator_shared_group_membership():
    res = client.get("/api/simulator/users")
    assert res.status_code == 200
    token_marco = client.post("/api/simulator/switch-user", json={"user_key": "marco"}).json()["access_token"]
    token_laura = client.post("/api/simulator/switch-user", json={"user_key": "laura"}).json()["access_token"]

    # Both Marco and Laura must see the shared group in /api/groups
    res_m = client.get("/api/groups", headers={"Authorization": f"Bearer {token_marco}"})
    assert res_m.status_code == 200
    groups_m = res_m.json() if isinstance(res_m.json(), list) else res_m.json().get("groups", [])
    assert len(groups_m) > 0

    res_l = client.get("/api/groups", headers={"Authorization": f"Bearer {token_laura}"})
    assert res_l.status_code == 200
    groups_l = res_l.json() if isinstance(res_l.json(), list) else res_l.json().get("groups", [])
    assert len(groups_l) > 0

    # Group IDs should match so they can test chatting together
    group_ids_m = {g["id"] for g in groups_m}
    group_ids_l = {g["id"] for g in groups_l}
    assert len(group_ids_m.intersection(group_ids_l)) > 0
