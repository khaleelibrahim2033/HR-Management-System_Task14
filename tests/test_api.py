from collections.abc import Generator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.config import settings
from app.models import Role, User
from app.security import hash_password


def test_openapi_groups_endpoints_by_module():
    schema = app.openapi()
    assert schema["paths"]["/auth/login"]["post"]["tags"] == ["Auth"]
    assert schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "/auth/login"
    assert schema["paths"]["/employees"]["get"]["tags"] == ["Employees"]
    assert schema["paths"]["/attendance"]["get"]["tags"] == ["Attendance"]
    assert schema["paths"]["/leaves"]["get"]["tags"] == ["Leaves"]


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    testing_session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_public_registration_is_employee_and_can_login(client: TestClient):
    response = client.post("/auth/register", json={
        "username": "employee1", "email": "employee1@example.com", "password": "StrongPass123", "full_name": "Employee One",
    })
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "EMPLOYEE"
    login = client.post("/auth/login", data={"username": "employee1", "password": "StrongPass123"})
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_employee_cannot_create_employee(client: TestClient):
    response = client.post("/auth/register", json={
        "username": "employee2", "email": "employee2@example.com", "password": "StrongPass123", "full_name": "Employee Two",
    })
    token = response.json()["access_token"]
    create = client.post("/employees", headers={"Authorization": f"Bearer {token}"}, json={})
    assert create.status_code == 403


def test_employee_can_check_in_and_apply_for_leave(client: TestClient):
    response = client.post("/auth/register", json={
        "username": "employee3", "email": "employee3@example.com", "password": "StrongPass123", "full_name": "Employee Three",
    })
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/employees", headers=headers)
    assert profile.status_code == 200
    assert len(profile.json()) == 1
    assert client.get(f"/employees/{profile.json()[0]['id']}", headers=headers).status_code == 200
    check_in = client.post("/attendance/check-in", headers=headers)
    assert check_in.status_code == 201
    assert check_in.json()["status"] == "PRESENT"
    assert isinstance(check_in.json()["is_late"], bool)
    assert client.post("/attendance/check-in", headers=headers).status_code == 409
    start = date.today() + timedelta(days=5)
    leave = client.post("/leaves", headers=headers, json={
        "leave_type": "CASUAL", "start_date": start.isoformat(), "end_date": (start + timedelta(days=1)).isoformat(), "reason": "Personal appointment",
    })
    assert leave.status_code == 201
    assert leave.json()["status"] == "PENDING"
    assert client.patch(f"/leaves/{leave.json()['id']}", headers=headers, json={"status": "APPROVED"}).status_code == 403
    other = client.post("/auth/register", json={
        "username": "employee4", "email": "employee4@example.com", "password": "StrongPass123", "full_name": "Employee Four",
    }).json()
    assert client.get(f"/employees/{profile.json()[0]['id']}", headers={"Authorization": f"Bearer {other['access_token']}"}).status_code == 403


def test_admin_can_onboard_review_and_generate_payroll(client: TestClient):
    session_generator = app.dependency_overrides[get_db]()
    db = next(session_generator)
    db.add(User(
        username="admin", email="admin@example.com", hashed_password=hash_password("StrongPass123"), role=Role.ADMIN,
    ))
    db.commit()
    session_generator.close()

    admin_login = client.post("/auth/login", data={"username": "admin", "password": "StrongPass123"})
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    created = client.post("/employees", headers=admin_headers, json={
        "username": "newemployee", "email": "newemployee@example.com", "password": "StrongPass123",
        "full_name": "New Employee", "designation": "Analyst", "department": "Finance",
        "joining_date": date.today().isoformat(), "salary": 5000,
    })
    assert created.status_code == 201
    employee_id = created.json()["id"]
    employee_login = client.post("/auth/login", data={"username": "newemployee", "password": "StrongPass123"})
    employee_headers = {"Authorization": f"Bearer {employee_login.json()['access_token']}"}

    start = date.today() + timedelta(days=5)
    leave = client.post("/leaves", headers=employee_headers, json={
        "leave_type": "PAID", "start_date": start.isoformat(), "end_date": start.isoformat(), "reason": "Family event",
    })
    reviewed = client.patch(f"/leaves/{leave.json()['id']}", headers=admin_headers, json={"status": "APPROVED"})
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "APPROVED"
    balances = client.get("/leave-balances", headers=employee_headers)
    assert balances.status_code == 200
    assert next(row for row in balances.json() if row["leave_type"] == "PAID")["remaining_days"] == 14

    payroll = client.post("/payroll", headers=admin_headers, json={
        "employee_id": employee_id, "month": date.today().strftime("%Y-%m"),
        "basic_salary": 5000, "allowances": 250, "deductions": 500, "bonus": 100,
    })
    assert payroll.status_code == 201
    assert payroll.json()["net_salary"] == 4850
    assert payroll.json()["allowances"] == 250
    assert len(client.get("/payroll", headers=employee_headers).json()) == 1
    notification_titles = [item["title"] for item in client.get("/notifications", headers=employee_headers).json()]
    assert "Leave approved" in notification_titles
    assert "Payroll generated" in notification_titles


def test_role_change_invalidates_existing_token(client: TestClient):
    session_generator = app.dependency_overrides[get_db]()
    db = next(session_generator)
    db.add(User(
        username="admin2", email="admin2@example.com", hashed_password=hash_password("StrongPass123"), role=Role.ADMIN,
    ))
    db.commit()
    session_generator.close()
    admin = client.post("/auth/login", data={"username": "admin2", "password": "StrongPass123"}).json()
    employee = client.post("/auth/register", json={
        "username": "rolechange", "email": "rolechange@example.com",
        "password": "StrongPass123", "full_name": "Role Change",
    }).json()
    employee_id = employee["user"]["id"]
    changed = client.patch(
        f"/auth/users/{employee_id}", headers={"Authorization": "Bearer " + admin["access_token"]},
        json={"role": "HR"},
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "HR"
    assert client.get(
        "/auth/me", headers={"Authorization": "Bearer " + employee["access_token"]},
    ).status_code == 401
    assert client.post("/auth/login", data={"username": "rolechange", "password": "StrongPass123"}).status_code == 200


def test_leave_balances_prevent_overuse_and_deduct_on_approval(client: TestClient):
    session_generator = app.dependency_overrides[get_db]()
    db = next(session_generator)
    db.add(User(
        username="leaveadmin", email="leaveadmin@example.com",
        hashed_password=hash_password("StrongPass123"), role=Role.ADMIN,
    ))
    db.commit()
    session_generator.close()
    admin = client.post("/auth/login", data={"username": "leaveadmin", "password": "StrongPass123"}).json()
    admin_headers = {"Authorization": "Bearer " + admin["access_token"]}
    employee = client.post("/auth/register", json={
        "username": "leaveuser", "email": "leaveuser@example.com",
        "password": "StrongPass123", "full_name": "Leave User",
    }).json()
    employee_headers = {"Authorization": "Bearer " + employee["access_token"]}
    start = date.today() + timedelta(days=10)
    overuse = client.post("/leaves", headers=employee_headers, json={
        "leave_type": "SICK", "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=10)).isoformat(), "reason": "Extended recovery",
    })
    assert overuse.status_code == 409
    request = client.post("/leaves", headers=employee_headers, json={
        "leave_type": "SICK", "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=5)).isoformat(), "reason": "Recovery",
    })
    assert request.status_code == 201
    approved = client.patch(
        f"/leaves/{request.json()['id']}", headers=admin_headers, json={"status": "APPROVED"},
    )
    assert approved.status_code == 200
    balances = client.get("/leave-balances", headers=employee_headers).json()
    assert next(row for row in balances if row["leave_type"] == "SICK")["remaining_days"] == 4
    excess_after_approval = client.post("/leaves", headers=employee_headers, json={
        "leave_type": "SICK", "start_date": (start + timedelta(days=20)).isoformat(),
        "end_date": (start + timedelta(days=24)).isoformat(), "reason": "More recovery",
    })
    assert excess_after_approval.status_code == 409


def test_phase_three_shift_calendar_documents_performance_and_reports(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "document_storage_dir", str(tmp_path))
    session_generator = app.dependency_overrides[get_db]()
    db = next(session_generator)
    db.add(User(
        username="phase3admin", email="phase3admin@example.com",
        hashed_password=hash_password("StrongPass123"), role=Role.ADMIN,
    ))
    db.commit()
    session_generator.close()
    admin_login = client.post("/auth/login", data={"username": "phase3admin", "password": "StrongPass123"}).json()
    admin_headers = {"Authorization": "Bearer " + admin_login["access_token"]}
    employee_login = client.post("/auth/register", json={
        "username": "phase3employee", "email": "phase3employee@example.com",
        "password": "StrongPass123", "full_name": "Phase Three Employee",
    }).json()
    employee_headers = {"Authorization": "Bearer " + employee_login["access_token"]}
    employee_id = client.get("/employees", headers=employee_headers).json()[0]["id"]

    assert client.post("/shifts", headers=employee_headers, json={
        "name": "Unauthorized shift", "start_time": "09:00", "end_time": "17:00",
    }).status_code == 403
    shift = client.post("/shifts", headers=admin_headers, json={
        "name": "Overnight", "start_time": "00:00", "end_time": "23:59",
    })
    assert shift.status_code == 201
    assigned = client.post("/employee-shifts", headers=admin_headers, json={
        "employee_id": employee_id, "shift_id": shift.json()["id"],
    })
    assert assigned.status_code == 201
    assert client.get("/employee-shifts", headers=employee_headers).json()[0]["shift_name"] == "Overnight"

    attendance = client.post("/attendance/check-in", headers=employee_headers)
    assert attendance.status_code == 201
    assert attendance.json()["is_late"] is True
    checkout = client.post("/attendance/check-out", headers=employee_headers)
    assert checkout.status_code == 200
    assert checkout.json()["is_early_out"] is True
    assert "Late attendance detected" in [
        row["title"] for row in client.get("/notifications", headers=employee_headers).json()
    ]
    assert "Late attendance alert" in [
        row["title"] for row in client.get("/notifications", headers=admin_headers).json()
    ]
    attendance_history = client.get("/attendance", headers=employee_headers).json()
    assert any(row["status"] == "ABSENT" for row in attendance_history)

    review = client.post("/performance", headers=admin_headers, json={
        "employee_id": employee_id, "review_period": "2026 Q4", "rating": 4.5, "feedback": "Excellent work.",
    })
    assert review.status_code == 201
    assert client.get("/performance", headers=employee_headers).json()[0]["rating"] == 4.5
    assert len(client.get("/employees?performance_min_rating=4", headers=admin_headers).json()) == 1
    assert len(client.get("/employees?role=EMPLOYEE&department=Unassigned", headers=admin_headers).json()) == 1

    start = date.today() + timedelta(days=2)
    leave = client.post("/leaves", headers=employee_headers, json={
        "leave_type": "CASUAL", "start_date": start.isoformat(), "end_date": start.isoformat(),
        "reason": "Personal time",
    })
    assert leave.status_code == 201
    calendar = client.get(
        f"/leaves/calendar?start_date={start.isoformat()}&end_date={start.isoformat()}",
        headers=admin_headers,
    )
    assert calendar.status_code == 200
    assert calendar.json()[0]["employee_name"] == "Phase Three Employee"

    uploaded = client.post(
        f"/documents?employee_id={employee_id}", headers=admin_headers,
        files={"file": ("identity.pdf", b"%PDF-1.4 test document", "application/pdf")},
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["id"]
    assert client.get("/documents", headers=employee_headers).json()[0]["file_name"] == "identity.pdf"
    assert client.get(f"/documents/{document_id}/download", headers=employee_headers).content == b"%PDF-1.4 test document"
    second_employee = client.post("/auth/register", json={
        "username": "phase3other", "email": "phase3other@example.com",
        "password": "StrongPass123", "full_name": "Other Employee",
    }).json()
    second_headers = {"Authorization": "Bearer " + second_employee["access_token"]}
    assert client.get(f"/documents/{document_id}/download", headers=second_headers).status_code == 403

    report = client.get(
        f"/reports/analytics?start_date={date.today().isoformat()}&end_date={date.today().isoformat()}",
        headers=admin_headers,
    )
    assert report.status_code == 200
    assert report.json()["performance_by_department"][0]["average_rating"] == 4.5
    assert any(row["status"] == "LATE" for row in report.json()["attendance_trends"])
