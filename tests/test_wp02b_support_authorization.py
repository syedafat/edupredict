from bson import ObjectId

from models import mongo


def _login(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = str(user_id)
        sess["role"] = role


def _seed_user(user_id, role):
    mongo.db.users.insert_one({
        "_id": user_id,
        "email": f"{user_id}@support-test.invalid",
        "role": role,
        "status": "approved",
    })


def test_student_can_reply_to_own_ticket_but_cannot_change_status(client):
    student_id = ObjectId()
    _seed_user(student_id, "student")
    ticket_id = mongo.db.support_tickets.insert_one({
        "created_by": str(student_id), "subject": "Help", "message": "Question", "status": "open",
    }).inserted_id
    _login(client, student_id, "student")

    response = client.post(
        f"/support/ticket/{ticket_id}/respond",
        data={"message": "Here is more detail", "status": "closed"},
    )

    ticket = mongo.db.support_tickets.find_one({"_id": ticket_id})
    assert response.status_code == 302
    assert ticket["status"] == "open"
    assert ticket["responses"][0]["message"] == "Here is more detail"


def test_student_cannot_reply_to_another_students_ticket(client):
    student_id, owner_id = ObjectId(), ObjectId()
    _seed_user(student_id, "student")
    _seed_user(owner_id, "student")
    ticket_id = mongo.db.support_tickets.insert_one({
        "created_by": str(owner_id), "subject": "Help", "message": "Question", "status": "open",
    }).inserted_id
    _login(client, student_id, "student")

    response = client.post(
        f"/support/ticket/{ticket_id}/respond", data={"message": "intrusion"},
    )

    assert response.status_code == 404
    assert "responses" not in mongo.db.support_tickets.find_one({"_id": ticket_id})


def test_analyst_cannot_view_ticket_outside_authorized_student_scope(client, monkeypatch):
    analyst_id, owner_id = ObjectId(), ObjectId()
    _seed_user(analyst_id, "analyst")
    _seed_user(owner_id, "student")
    ticket_id = mongo.db.support_tickets.insert_one({
        "created_by": str(owner_id), "subject": "Help", "message": "Question", "status": "open",
    }).inserted_id
    _login(client, analyst_id, "analyst")
    monkeypatch.setattr(
        "routes.support_routes.AcademicDataService.analyst_student_ids",
        lambda _analyst_id: set(),
    )

    response = client.get(f"/support/ticket/{ticket_id}")

    assert response.status_code == 404
