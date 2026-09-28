"""
Test suite per l'endpoint di healthcheck e la configurazione di deployment Railway/Docker.
"""
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check_endpoint():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "database" in data
    assert "timestamp" in data


def test_deployment_manifests_exist():
    base_dir = Path(__file__).resolve().parent.parent
    dockerfile = base_dir / "Dockerfile"
    railway_json = base_dir / "railway.json"

    assert dockerfile.exists(), "Dockerfile non trovato nella root del progetto"
    assert railway_json.exists(), "railway.json non trovato nella root del progetto"

    docker_content = dockerfile.read_text(encoding="utf-8")
    assert "python" in docker_content.lower()
    assert "uvicorn" in docker_content.lower()

    railway_content = railway_json.read_text(encoding="utf-8")
    assert "build" in railway_content.lower()
