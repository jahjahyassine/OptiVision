"""
tests/test_face_recognition.py
===============================
Pytest test suite for the face recognition module.

Run all:
    pytest tests/test_face_recognition.py -v

Skip integration tests (no model download needed):
    pytest tests/test_face_recognition.py -v -m "not integration"
"""

from __future__ import annotations

import io

import numpy as np
import pytest

from backend.ai_modules.face_recognition.embedding_db import EmbeddingDB, EMBEDDING_DIM


# ─────────────────────────────── helpers ─────────────────────────────────────

def make_embedding(seed: int = 0) -> np.ndarray:
    """Reproducible unit-length random embedding."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def db(tmp_path):
    return EmbeddingDB(tmp_path / "test.db")


# ─────────────────────────────── DB unit tests ───────────────────────────────

class TestEmbeddingDB:

    def test_empty_returns_none(self, db):
        name, sim = db.find_closest(make_embedding())
        assert name is None and sim == 0.0

    def test_add_and_count(self, db):
        db.add_face("Alice", make_embedding(1))
        assert db.count() == 1
        assert db.person_count() == 1

    def test_multiple_embeddings_same_person(self, db):
        db.add_face("Bob", make_embedding(10))
        db.add_face("Bob", make_embedding(11))
        assert db.count() == 2
        assert db.person_count() == 1

    def test_exact_match_returns_one(self, db):
        emb = make_embedding(42)
        db.add_face("TestPerson", emb)
        name, sim = db.find_closest(emb)
        assert name == "TestPerson"
        assert sim == pytest.approx(1.0, abs=1e-5)

    def test_correct_person_returned(self, db):
        alice_emb = make_embedding(1)
        bob_emb = make_embedding(999)   # very different direction
        db.add_face("Alice", alice_emb)
        db.add_face("Bob",   bob_emb)

        # tiny perturbation of Alice → should still return Alice
        query = alice_emb + 1e-6 * make_embedding(7)
        name, sim = db.find_closest(query)
        assert name == "Alice"
        assert sim > 0.99

    def test_delete_person(self, db):
        db.add_face("Alice", make_embedding(1))
        db.add_face("Alice", make_embedding(2))
        db.add_face("Bob",   make_embedding(3))
        deleted = db.delete_person("Alice")
        assert deleted == 2
        assert db.person_count() == 1

    def test_delete_nonexistent_is_zero(self, db):
        assert db.delete_person("Nobody") == 0

    def test_list_all(self, db):
        db.add_face("Alice", make_embedding(1), "friend")
        db.add_face("Bob",   make_embedding(2), "colleague")
        names = {p["name"] for p in db.list_all()}
        assert names == {"Alice", "Bob"}

    def test_top_k_ordering(self, db):
        for i, name in enumerate(["Alice", "Bob", "Carol"]):
            db.add_face(name, make_embedding(i * 100))

        results = db.find_top_k(make_embedding(0), k=2)
        assert len(results) == 2
        assert results[0][0] == "Alice"          # seed-0 == seed-0 → sim ≈ 1.0
        assert results[0][1] == pytest.approx(1.0, abs=1e-5)

    def test_unnormalised_embedding_still_works(self, db):
        """Raw embeddings (any magnitude) should be normalised on store."""
        raw = np.ones(EMBEDDING_DIM, dtype=np.float32) * 7.0
        db.add_face("Test", raw)
        name, sim = db.find_closest(raw)
        assert sim == pytest.approx(1.0, abs=1e-5)

    def test_clear(self, db):
        db.add_face("Alice", make_embedding(1))
        db.clear()
        assert db.count() == 0

    def test_threshold_boundary(self, db):
        """A perpendicular vector should yield very low similarity."""
        from backend.ai_modules.face_recognition.recognizer import SIMILARITY_THRESHOLD

        alice = make_embedding(1)
        db.add_face("Alice", alice)

        # Build a vector orthogonal to Alice via Gram-Schmidt
        noise = make_embedding(77)
        perp = noise - np.dot(noise, alice) * alice
        perp = perp / np.linalg.norm(perp)

        name, sim = db.find_closest(perp.astype(np.float32))
        assert name == "Alice"           # closest match...
        assert sim < SIMILARITY_THRESHOLD  # ...but below threshold → Unknown


# ─────────────────────────────── integration tests ───────────────────────────

@pytest.mark.integration
class TestFaceRecognizerIntegration:
    """
    Requires InsightFace buffalo_sc (~30 MB) to be downloaded.
    Skip: pytest -m "not integration"
    """

    @pytest.fixture(scope="class")
    def rec(self, tmp_path_factory):
        from ai_modules.face_recognition import FaceRecognizer
        return FaceRecognizer(
            db_path=tmp_path_factory.mktemp("data") / "faces.db",
            ctx_id=-1,
            model_name="buffalo_sc",
        )

    def test_blank_frame_returns_empty(self, rec):
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        assert rec.process(blank) == []

    def test_none_frame_returns_empty(self, rec):
        assert rec.process(None) == []

    def test_result_keys_present(self, rec):
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        for r in rec.process(blank):
            assert {"name", "label", "confidence", "bbox", "known"} <= r.keys()
            assert len(r["bbox"]) == 4

    def test_real_photo_enrollment_and_recognition(self, rec):
        """
        Uncomment and point at real photos to run a full accuracy test:

        ok = rec.enroll_from_image_path("tests/assets/john_front.jpg", "John", "friend")
        assert ok

        import cv2
        frame = cv2.imread("tests/assets/john_test.jpg")
        results = rec.process(frame)
        assert any(r["name"] == "John" and r["known"] for r in results)
        """
        pass   # placeholder — requires real face photos


# ─────────────────────────────── API tests ───────────────────────────────────

@pytest.mark.integration
class TestFacesAPI:
    """FastAPI endpoint smoke tests."""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.api.routes.faces import router
        app = FastAPI()
        app.include_router(router, prefix="/api/faces")
        return TestClient(app)

    def test_list_empty(self, client):
        r = client.get("/api/faces/")
        assert r.status_code == 200
        assert "persons" in r.json()

    def test_enroll_blank_image_returns_422(self, client):
        import cv2
        blank = np.zeros((100, 100, 3), dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", blank)
        r = client.post(
            "/api/faces/enroll",
            files={"image": ("blank.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")},
            data={"name": "Test", "relationship": ""},
        )
        assert r.status_code == 422

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/faces/PersonXYZ999")
        assert r.status_code == 404