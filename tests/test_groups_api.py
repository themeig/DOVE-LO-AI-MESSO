"""
Test suite per le API di gestione gruppi, adesione tramite codice invito e verifica permessi.
"""
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db
from app.services.auth_service import get_current_user

client = TestClient(app)


def setup_module():
    init_db()


def test_create_and_join_group(monkeypatch):
    # Mock auth user 1 (creatore)
    user1 = {"id": "user-test-1", "sub": "user-test-1", "email": "admin@test.it", "full_name": "Admin Test"}
    app.dependency_overrides[get_current_user] = lambda: user1

    # 1. Creazione gruppo
    res = client.post("/api/groups", json={"name": "Casa Mare", "description": "Spese condivise"})
    assert res.status_code == 201
    group_data = res.json()
    invite_code = group_data["invite_code"]
    group_id = group_data["id"]
    assert group_data["name"] == "Casa Mare"
    assert invite_code is not None

    # 2. Elenco gruppi per user 1
    res_list = client.get("/api/groups")
    assert res_list.status_code == 200
    groups = res_list.json()
    assert any(g["id"] == group_id for g in groups)

    # 3. Adesione gruppo con user 2 tramite invite_code
    user2 = {"id": "user-test-2", "sub": "user-test-2", "email": "ospite@test.it", "full_name": "Ospite Test"}
    app.dependency_overrides[get_current_user] = lambda: user2

    join_res = client.post("/api/groups/join", json={"invite_code": invite_code})
    assert join_res.status_code == 200
    assert join_res.json()["group_id"] == group_id

    # 4. Lettura membri del gruppo come user 2
    members_res = client.get(f"/api/groups/{group_id}/members")
    assert members_res.status_code == 200
    members = members_res.json()
    assert len(members) == 2
    emails = [m["email"] for m in members]
    assert "admin@test.it" in emails
    assert "ospite@test.it" in emails

    # 5. Tentativo di accesso da user 3 non appartenente al gruppo -> 403 Forbidden
    user3 = {"id": "user-test-3", "sub": "user-test-3", "email": "estraneo@test.it", "full_name": "Estraneo"}
    app.dependency_overrides[get_current_user] = lambda: user3

    unauth_res = client.get(f"/api/groups/{group_id}/members")
    assert unauth_res.status_code == 403

    # 6. Join con codice inesistente -> 404 Not Found
    invalid_join = client.post("/api/groups/join", json={"invite_code": "NON-ESISTE-99"})
    assert invalid_join.status_code == 404

    # Pulizia overrides
    app.dependency_overrides.clear()
