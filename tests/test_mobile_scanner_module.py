# tests/test_mobile_scanner_module.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_mobile_scanner_js_asset_exists():
    res = client.get("/static/js/mobile-scanner.js")
    assert res.status_code == 200
    assert "MobileScanner" in res.text
    assert "applyPerspectiveWarp" in res.text
    assert "getUserMedia" in res.text
    assert "requestMobilePermission" in res.text

def test_multiphoto_components_in_html_and_bundle():
    # Verify mobile.html and index.html have cameraMultiPhotoInput and multiPhotoModal
    for endpoint in ["/m", "/"]:
        res = client.get(endpoint, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, follow_redirects=True)
        assert res.status_code == 200
        html = res.text
        assert 'id="cameraMultiPhotoInput"' in html
        assert 'id="galleryMultiPhotoInput"' in html
        assert 'id="multiPhotoModal"' in html
        assert 'id="multiPhotoGrid"' in html

    # Verify app-bundle.js contains multi-photo session functions
    res_bundle = client.get("/static/js/app-bundle.js")
    assert res_bundle.status_code == 200
    bundle_text = res_bundle.text
    assert "handleCameraMultiPhotoSelected" in bundle_text
    assert "submitMultiPhotosAsPdf" in bundle_text
    assert "submitMultiPhotosSeparately" in bundle_text
    assert "triggerAnotherCameraShot" in bundle_text

