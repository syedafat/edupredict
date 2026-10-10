"""WP-02A Regression Tests — IDOR-01 & IDOR-02 Authorization Hardening.

Tests are plain pytest functions that receive the ``client`` fixture so that
pytest can inject it directly.

Covers:
  IDOR-01: POST /data/stream — teachers/analysts may not ingest events for
           students outside their authorized scope.
  IDOR-02: POST /ml/predict/<model_type> — analysts may not generate
           predictions for students outside their authorized scope.

Design notes
------------
* Uses plain pytest functions (matching the pattern in tests/auth/).
* Users are inserted into the mongomock database so the ``role_required``
  decorator's live MongoDB re-verification passes.
* ``AcademicDataService.is_user_authorized_for_student`` is patched at its
  source (``services.academic_data_service``) since it is locally imported
  inside route functions and therefore not accessible as a module-level
  attribute of the route modules.
* ``ProcessingService.process_stream_event`` is patched so the stream tests
  do not require a valid event payload on disk.
* Rate limiting is reset per test by the conftest ``client`` fixture.
* CSRF is globally disabled via conftest (WTF_CSRF_ENABLED = False).
* No real secrets are used or printed.
"""
import json
from unittest.mock import patch, MagicMock

import pytest
from bson import ObjectId

from models import mongo


# ---------------------------------------------------------------------------
# User fixtures — valid ObjectIds + matching records in mongomock
# ---------------------------------------------------------------------------

TEACHER_OID = ObjectId()
ANALYST_OID = ObjectId()
ADMIN_OID = ObjectId()

TEACHER_ID = str(TEACHER_OID)
ANALYST_ID = str(ANALYST_OID)
ADMIN_ID = str(ADMIN_OID)

AUTHORIZED_STUDENT = "student-in-roster"
UNAUTHORIZED_STUDENT = "student-not-in-roster"
FEATURES = [0.5, 0.6, 0.7, 0.8]

_USERS = [
    {"_id": TEACHER_OID, "name": "Test Teacher", "email": "teacher@test.com",
     "role": "teacher", "status": "approved"},
    {"_id": ANALYST_OID, "name": "Test Analyst", "email": "analyst@test.com",
     "role": "analyst", "status": "approved"},
    {"_id": ADMIN_OID, "name": "Test Admin", "email": "admin@test.com",
     "role": "admin", "status": "approved"},
]


@pytest.fixture(autouse=True)
def seed_users():
    """Insert test users before each test and remove them afterwards.
    Also clears stream_events and predictions so no-write assertions are clean."""
    mongo.db.users.delete_many({})
    mongo.db.stream_events.delete_many({})
    mongo.db.predictions.delete_many({})
    mongo.db.users.insert_many(_USERS)
    yield
    mongo.db.users.delete_many({})
    mongo.db.stream_events.delete_many({})
    mongo.db.predictions.delete_many({})


# ---------------------------------------------------------------------------
# Helper — set a signed session on the test client
# ---------------------------------------------------------------------------

def _set_session(client, user_id: str, role: str):
    """Push user_id and role into the Flask test client session."""
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["role"] = role


# ---------------------------------------------------------------------------
# Fake stream event returned by ProcessingService.process_stream_event
# ---------------------------------------------------------------------------

def _fake_event(student_id: str) -> dict:
    return {
        "student_id": student_id,
        "event_type": "login",
        "value": 1,
        "received_at": "2026-01-01T00:00:00Z",
    }


# ===========================================================================
# IDOR-01: POST /data/stream
# ===========================================================================

STREAM_ENDPOINT = "/data/stream"


def _post_stream(client, student_id):
    payload = {"student_id": student_id, "event_type": "login", "value": 1}
    return client.post(
        STREAM_ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_stream_teacher_authorized_student_returns_201(client):
    """IDOR-01: A teacher authorized for a student receives 201 Created."""
    _set_session(client, TEACHER_ID, "teacher")
    with patch(
        "services.academic_data_service.AcademicDataService.is_user_authorized_for_student",
        return_value=True,
    ), patch(
        "services.processing_service.ProcessingService.process_stream_event",
        return_value=_fake_event(AUTHORIZED_STUDENT),
    ), patch("routes.data_routes.AlertService"):
        resp = _post_stream(client, AUTHORIZED_STUDENT)
    assert resp.status_code == 201


def test_stream_teacher_unauthorized_student_returns_403(client):
    """IDOR-01: A teacher NOT authorized for a student receives 403."""
    _set_session(client, TEACHER_ID, "teacher")
    with patch(
        "services.academic_data_service.AcademicDataService.is_user_authorized_for_student",
        return_value=False,
    ), patch(
        "services.processing_service.ProcessingService.process_stream_event",
        return_value=_fake_event(UNAUTHORIZED_STUDENT),
    ) as process_event:
        resp = _post_stream(client, UNAUTHORIZED_STUDENT)
    assert resp.status_code == 403
    process_event.assert_not_called()


def test_stream_teacher_unauthorized_no_db_write(client):
    """IDOR-01: Unauthorized stream event must NOT be written to the database."""
    _set_session(client, TEACHER_ID, "teacher")
    with patch(
        "services.academic_data_service.AcademicDataService.is_user_authorized_for_student",
        return_value=False,
    ), patch(
        "services.processing_service.ProcessingService.process_stream_event",
        return_value=_fake_event(UNAUTHORIZED_STUDENT),
    ) as process_event:
        _post_stream(client, UNAUTHORIZED_STUDENT)
    # Mongomock DB should have no stream events inserted
    assert mongo.db.stream_events.count_documents({}) == 0
    process_event.assert_not_called()


def test_stream_analyst_unauthorized_student_returns_403(client):
    """IDOR-01: An analyst NOT authorized for a student receives 403."""
    _set_session(client, ANALYST_ID, "analyst")
    with patch(
        "services.academic_data_service.AcademicDataService.is_user_authorized_for_student",
        return_value=False,
    ), patch(
        "services.processing_service.ProcessingService.process_stream_event",
        return_value=_fake_event(UNAUTHORIZED_STUDENT),
    ):
        resp = _post_stream(client, UNAUTHORIZED_STUDENT)
    assert resp.status_code == 403


def test_stream_admin_authorized_student_returns_201(client):
    """IDOR-01: An admin may ingest events for any student."""
    _set_session(client, ADMIN_ID, "admin")
    with patch(
        "services.academic_data_service.AcademicDataService.is_user_authorized_for_student",
        return_value=True,
    ), patch(
        "services.processing_service.ProcessingService.process_stream_event",
        return_value=_fake_event(AUTHORIZED_STUDENT),
    ), patch("routes.data_routes.AlertService"):
        resp = _post_stream(client, AUTHORIZED_STUDENT)
    assert resp.status_code == 201


def test_previously_logged_in_teacher_is_revoked_after_rejection(client):
    _set_session(client, TEACHER_ID, "teacher")
    mongo.db.users.update_one({"_id": TEACHER_OID}, {"$set": {"status": "rejected"}})

    response = client.get("/data/streaming")

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_previously_logged_in_pending_teacher_is_revoked(client):
    _set_session(client, TEACHER_ID, "teacher")
    mongo.db.users.update_one({"_id": TEACHER_OID}, {"$set": {"status": "pending"}})

    response = client.get("/data/streaming")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_stream_unauthenticated_rejected(client):
    """IDOR-01: Unauthenticated requests must be rejected (302 redirect to login)."""
    resp = _post_stream(client, AUTHORIZED_STUDENT)
    # role_required redirects unauthenticated users to /auth/login
    assert resp.status_code == 302


# ===========================================================================
# IDOR-02: POST /ml/predict/<model_type>
# ===========================================================================

PREDICT_ENDPOINT = "/ml/predict/performance"

_FAKE_TRAINING = {
    "model_type": "performance",
    "model_version": "v1",
    "feature_schema_version": "1",
    "model_data": None,
}


def _post_predict(client, student_id=None):
    payload = {"features": FEATURES}
    if student_id is not None:
        payload["student_id"] = student_id
    return client.post(
        PREDICT_ENDPOINT,
        data=json.dumps(payload),
        content_type="application/json",
    )


def _mock_mongo_for_predict(mock_mongo):
    """Set up standard mongomock returns needed for the predict route."""
    mock_mongo.db.trainings.find_one.return_value = _FAKE_TRAINING
    mock_mongo.db.predictions.insert_one.return_value = None
    mock_mongo.db.courses.find.return_value = []


def test_predict_teacher_authorized_student_not_403(client):
    """IDOR-02: A teacher authorized for a student does NOT receive 403."""
    _set_session(client, TEACHER_ID, "teacher")
    with patch(
        "services.academic_data_service.AcademicDataService.teacher_student_ids",
        return_value={AUTHORIZED_STUDENT},
    ), patch(
        "services.academic_data_service.AcademicDataService.validate_feature_record",
        return_value=None,
    ), patch("routes.ml_routes.mongo") as mock_mongo, \
       patch("routes.ml_routes.AlertService"), \
       patch("routes.ml_routes.AuditService"):
        _mock_mongo_for_predict(mock_mongo)
        resp = _post_predict(client, AUTHORIZED_STUDENT)
    assert resp.status_code != 403


def test_predict_teacher_unauthorized_student_returns_403(client):
    """IDOR-02: A teacher NOT authorized for a student receives 403."""
    _set_session(client, TEACHER_ID, "teacher")
    with patch(
        "routes.ml_routes.AcademicDataService.teacher_student_ids",
        return_value=set(),  # empty roster
    ):
        resp = _post_predict(client, UNAUTHORIZED_STUDENT)
    assert resp.status_code == 403


def test_predict_analyst_authorized_student_not_403(client):
    """IDOR-02: An analyst authorized for a student does NOT receive 403."""
    _set_session(client, ANALYST_ID, "analyst")
    with patch(
        "services.academic_data_service.AcademicDataService.is_user_authorized_for_student",
        return_value=True,
    ), patch(
        "services.academic_data_service.AcademicDataService.validate_feature_record",
        return_value=None,
    ), patch("routes.ml_routes.mongo") as mock_mongo, \
       patch("routes.ml_routes.AlertService"), \
       patch("routes.ml_routes.AuditService"):
        _mock_mongo_for_predict(mock_mongo)
        resp = _post_predict(client, AUTHORIZED_STUDENT)
    assert resp.status_code != 403


def test_predict_analyst_unauthorized_student_returns_403(client):
    """IDOR-02: An analyst NOT authorized for a student receives 403."""
    _set_session(client, ANALYST_ID, "analyst")
    with patch(
        "routes.ml_routes.AcademicDataService.is_user_authorized_for_student",
        return_value=False,
    ):
        resp = _post_predict(client, UNAUTHORIZED_STUDENT)
    assert resp.status_code == 403


def test_predict_analyst_unauthorized_no_db_write(client):
    """IDOR-02: Unauthorized prediction must NOT be inserted into the database."""
    _set_session(client, ANALYST_ID, "analyst")
    with patch(
        "services.academic_data_service.AcademicDataService.is_user_authorized_for_student",
        return_value=False,
    ):
        _post_predict(client, UNAUTHORIZED_STUDENT)
    assert mongo.db.predictions.count_documents({}) == 0


def test_predict_analyst_no_student_id_skips_idor_check(client):
    """IDOR-02: Analyst predictions with no student_id bypass the per-student
    IDOR check (institution-level aggregate prediction)."""
    _set_session(client, ANALYST_ID, "analyst")
    with patch(
        "services.academic_data_service.AcademicDataService.is_user_authorized_for_student",
    ) as mock_auth, \
       patch(
           "services.academic_data_service.AcademicDataService.validate_feature_record",
           return_value=None,
       ), patch("routes.ml_routes.mongo") as mock_mongo, \
       patch("routes.ml_routes.AlertService"), \
       patch("routes.ml_routes.AuditService"):
        _mock_mongo_for_predict(mock_mongo)
        resp = _post_predict(client, student_id=None)
    # The per-student authorization check must NOT have been called
    mock_auth.assert_not_called()
    assert resp.status_code != 403


def test_predict_unauthenticated_rejected(client):
    """IDOR-02: Unauthenticated requests must be redirected to login (302)."""
    resp = _post_predict(client, AUTHORIZED_STUDENT)
    assert resp.status_code == 302
