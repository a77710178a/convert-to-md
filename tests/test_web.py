from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from convert_to_md.webapp import app


@pytest.fixture()
def client():
    return TestClient(app)


def test_web_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "version" in data
    assert isinstance(data["formats"], list)


def test_web_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "convert-to-md" in r.text


def test_web_convert_preview_json(client, tmp_path: Path):
    # simple json upload
    content = b'{"hello": "web"}'
    files = {"file": ("demo.json", content, "application/json")}
    data = {
        "pdf_ocr": "off",
        "pdf_formula_ocr": "off",
        "formula_ocr_engine": "auto",
        "pdf_page_headings": "false",
        "html_keep_infobox": "false",
    }
    r = client.post("/api/convert-preview", files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["kind"] == "json"
    assert "hello" in body["preview"]


def test_web_convert_download_md(client):
    content = b"name,age\nAda,36\n"
    files = {"file": ("t.csv", content, "text/csv")}
    data = {
        "pdf_ocr": "off",
        "pdf_formula_ocr": "off",
        "formula_ocr_engine": "auto",
    }
    r = client.post("/api/convert", files=files, data=data)
    assert r.status_code == 200, r.text
    assert "Ada" in r.text or "age" in r.text
    assert "markdown" in (r.headers.get("content-type") or "") or r.content


def test_web_convert_batch_zip(client):
    files = [
        ("files", ("a.json", b'{"a":1}', "application/json")),
        ("files", ("b.csv", b"x,y\n1,2\n", "text/csv")),
    ]
    data = {
        "pdf_ocr": "off",
        "pdf_formula_ocr": "off",
        "formula_ocr_engine": "auto",
    }
    r = client.post("/api/convert-batch", files=files, data=data)
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/zip")
    assert r.headers.get("X-Convert-Ok") == "2"
    assert r.headers.get("X-Convert-Failed") == "0"
    assert r.content[:2] == b"PK"


def test_web_job_progress_and_download(client):
    import time

    files = [
        ("files", ("a.json", b'{"a":1}', "application/json")),
        ("files", ("b.csv", b"x,y\n1,2\n", "text/csv")),
    ]
    data = {
        "pdf_ocr": "off",
        "pdf_formula_ocr": "off",
        "formula_ocr_engine": "auto",
    }
    r = client.post("/api/jobs", files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    job_id = body["job"]["id"]

    final = None
    for _ in range(50):
        s = client.get(f"/api/jobs/{job_id}")
        assert s.status_code == 200
        final = s.json()["job"]
        if final["status"] in {"done", "error"}:
            break
        time.sleep(0.05)
    assert final is not None
    assert final["status"] == "done"
    assert final["ok"] == 2
    assert final["download_ready"] is True

    d = client.get(f"/api/jobs/{job_id}/download")
    assert d.status_code == 200
    assert d.headers.get("content-type", "").startswith("application/zip")
    assert d.content[:2] == b"PK"
