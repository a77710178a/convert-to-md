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
