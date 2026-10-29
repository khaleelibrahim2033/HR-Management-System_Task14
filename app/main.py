from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import os

import jwt
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import (
    Attendance, AttendanceStatus, Employee, EmployeeStatus, Leave, LeaveBalance, LeavePolicy, LeaveStatus,
    LeaveType, Notification, Payroll, Role, User, Shift, EmployeeShift, Document, Performance,
)
from .schemas import (
    AdminUserCreate, AdminUserUpdate, AttendanceMark, AttendanceOut, EmployeeCreate, EmployeeOut, EmployeeUpdate,
    LeaveBalanceOut, LeaveCreate, LeaveOut, LeavePolicyCreate, LeavePolicyOut, LeavePolicyUpdate, LeaveReview,
    NotificationOut, PayrollCreate, PayrollOut, RegisterInput, TokenOut, UserOut, ShiftCreate, ShiftOut,
    EmployeeShiftAssign, EmployeeShiftOut, DocumentOut, PerformanceCreate, PerformanceOut,
)
from .models import Onboarding, OnboardingStatus, Resignation, ResignationStatus, Announcement, InternalTask, InternalTaskStatus, Feedback, NotificationPreference
from .security import create_access_token, hash_password, verify_password

Base.metadata.create_all(bind=engine)


def migrate_existing_schema() -> None:
    migrations = {
        "users": {"is_active": "BOOLEAN NOT NULL DEFAULT 1"},
        "attendance": {
            "is_late": "BOOLEAN NOT NULL DEFAULT 0",
            "is_early": "BOOLEAN NOT NULL DEFAULT 0",
            "is_early_out": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "payroll": {"allowances": "FLOAT NOT NULL DEFAULT 0"},
    }
    with engine.begin() as connection:
        for table, columns in migrations.items():
            existing = {column["name"] for column in inspect(connection).get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


migrate_existing_schema()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap_admin()
    yield


app = FastAPI(
    title="WorkSphere HRMS",
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Health", "description": "Service status"},
        {"name": "Auth", "description": "Registration, sign-in, and user accounts"},
        {"name": "Employees", "description": "Employee profiles and directory"},
        {"name": "Attendance", "description": "Check-in, check-out, and attendance records"},
        {"name": "Shifts", "description": "Shift configuration, assignments, and schedules"},
        {"name": "Leaves", "description": "Leave requests and approvals"},
        {"name": "Documents", "description": "Protected employee document upload and access"},
        {"name": "Performance", "description": "Employee reviews, ratings, and feedback history"},
        {"name": "Payroll", "description": "Payroll records and payslips"},
        {"name": "Notifications", "description": "Personal notifications"},
        {"name": "Dashboard", "description": "HR and administrator analytics"},
        {"name": "Reports", "description": "Filtered HR analytics and department reports"},
        {"name": "Onboarding", "description": "Employee onboarding and checklists"},
        {"name": "Resignations", "description": "Employee resignation and exit management"},
        {"name": "Announcements", "description": "Internal company announcements"},
        {"name": "Tasks", "description": "Internal task assignment and tracking"},
        {"name": "Integrations", "description": "Email integration and report exports"},
        {"name": "Feedback", "description": "Employee feedback and ratings"},
        {"name": "Profile & Settings", "description": "Profile, password, and notification preferences"},
    ],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
        user_id = int(payload["sub"])
        token_role = Role(payload["role"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise unauthorized
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.role != token_role:
        raise unauthorized
    return user


def require_roles(*roles: Role):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action")
        return user
    return dependency


def get_employee(db: Session, user: User) -> Employee:
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    return employee


def employee_out(employee: Employee) -> dict:
    return {
        "id": employee.id, "user_id": employee.user_id, "full_name": employee.full_name,
        "designation": employee.designation, "department": employee.department,
        "joining_date": employee.joining_date, "salary": employee.salary, "status": employee.status,
        "username": employee.user.username, "email": employee.user.email,
        "role": employee.user.role,
    }


def attendance_out(row: Attendance) -> dict:
    hours = 0.0
    if row.check_in and row.check_out:
        start = row.check_in.replace(tzinfo=timezone.utc) if row.check_in.tzinfo is None else row.check_in
        end = row.check_out.replace(tzinfo=timezone.utc) if row.check_out.tzinfo is None else row.check_out
        hours = round(max(0, (end - start).total_seconds()) / 3600, 2)
    return {"id": row.id, "employee_id": row.employee_id, "check_in": row.check_in, "check_out": row.check_out,
            "date": row.date, "status": row.status, "is_late": row.is_late, "is_early": row.is_early,
            "is_early_out": row.is_early_out, "working_hours": hours, "employee_name": row.employee.full_name}


def is_late_check_in(check_in: datetime | None, shift: EmployeeShift | None) -> bool:
    if check_in is None:
        return False
    normalized = check_in.replace(tzinfo=timezone.utc) if check_in.tzinfo is None else check_in
    scheduled_start = shift.shift.start_time if shift else settings.attendance_late_after
    return normalized.astimezone().time().replace(tzinfo=None) > scheduled_start


def is_early_check_in(check_in: datetime | None, shift: EmployeeShift | None) -> bool:
    if check_in is None or shift is None:
        return False
    normalized = check_in.replace(tzinfo=timezone.utc) if check_in.tzinfo is None else check_in
    return normalized.astimezone().time().replace(tzinfo=None) < shift.shift.start_time


def is_early_check_out(check_out: datetime | None, attendance_date: date,
                       shift: EmployeeShift | None) -> bool:
    if check_out is None or shift is None:
        return False
    normalized = check_out.replace(tzinfo=timezone.utc) if check_out.tzinfo is None else check_out
    local_checkout = normalized.astimezone()
    shift_end_date = attendance_date + timedelta(
        days=1 if shift.shift.end_time <= shift.shift.start_time else 0,
    )
    scheduled_end = datetime.combine(shift_end_date, shift.shift.end_time).astimezone()
    return local_checkout < scheduled_end


def leave_out(row: Leave) -> dict:
    return {"id": row.id, "employee_id": row.employee_id, "leave_type": row.leave_type,
            "start_date": row.start_date, "end_date": row.end_date, "reason": row.reason,
            "status": row.status, "created_at": row.created_at, "employee_name": row.employee.full_name}


def payroll_out(row: Payroll) -> dict:
    return {"id": row.id, "employee_id": row.employee_id, "basic_salary": row.basic_salary,
            "allowances": row.allowances, "deductions": row.deductions, "bonus": row.bonus, "net_salary": row.net_salary,
            "month": row.month, "created_at": row.created_at, "employee_name": row.employee.full_name}


def employee_shift_out(row: EmployeeShift) -> dict:
    return {
        "id": row.id, "employee_id": row.employee_id, "employee_name": row.employee.full_name,
        "department": row.employee.department, "shift_id": row.shift_id, "shift_name": row.shift.name,
        "start_time": row.shift.start_time, "end_time": row.shift.end_time,
    }


def document_out(row: Document) -> dict:
    return {
        "id": row.id, "employee_id": row.employee_id, "employee_name": row.employee.full_name,
        "file_name": row.file_name, "file_url": f"/documents/{row.id}/download", "uploaded_at": row.uploaded_at,
    }


def performance_out(row: Performance) -> dict:
    return {
        "id": row.id, "employee_id": row.employee_id, "employee_name": row.employee.full_name,
        "review_period": row.review_period, "rating": row.rating, "feedback": row.feedback,
        "created_at": row.created_at,
    }


def leave_days(start_date: date, end_date: date) -> int:
    return (end_date - start_date).days + 1


def ensure_leave_balances(db: Session, employee_id: int) -> None:
    policies = db.scalars(select(LeavePolicy)).all()
    balances = {
        balance.leave_type
        for balance in db.scalars(select(LeaveBalance).where(LeaveBalance.employee_id == employee_id)).all()
    }
    for policy in policies:
        if policy.leave_type not in balances:
            db.add(LeaveBalance(employee_id=employee_id, leave_type=policy.leave_type,
                                remaining_days=policy.total_days_allowed))
    db.flush()


def ensure_default_leave_policies(db: Session) -> None:
    defaults = {LeaveType.SICK: 10, LeaveType.CASUAL: 10, LeaveType.PAID: 15}
    for leave_type, days in defaults.items():
        if db.scalar(select(LeavePolicy).where(LeavePolicy.leave_type == leave_type)) is None:
            db.add(LeavePolicy(leave_type=leave_type, total_days_allowed=days))
    db.flush()


def ensure_default_shifts(db: Session) -> None:
    defaults = {
        "Morning": (time(9), time(17)),
        "Evening": (time(14), time(22)),
        "Night": (time(22), time(6)),
    }
    for name, (start_time, end_time) in defaults.items():
        if db.scalar(select(Shift.id).where(Shift.name == name)) is None:
            db.add(Shift(name=name, start_time=start_time, end_time=end_time))
    db.flush()


def notify(db: Session, user_id: int, title: str, message: str) -> None:
    db.add(Notification(user_id=user_id, title=title, message=message))


def notify_hr_users(db: Session, title: str, message: str) -> None:
    reviewers = db.scalars(select(User).where(
        User.role.in_([Role.HR, Role.ADMIN]), User.is_active.is_(True),
    )).all()
    for reviewer in reviewers:
        notify(db, reviewer.id, title, message)


def bootstrap_admin() -> None:
    with SessionLocal() as db:
        exists = db.scalar(select(User).where(User.role == Role.ADMIN))
        if exists is None and settings.bootstrap_admin_username and settings.bootstrap_admin_email and settings.bootstrap_admin_password:
            db.add(User(username=settings.bootstrap_admin_username, email=settings.bootstrap_admin_email,
                        hashed_password=hash_password(settings.bootstrap_admin_password), role=Role.ADMIN))
            db.flush()
        ensure_default_leave_policies(db)
        ensure_default_shifts(db)
        db.commit()


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


@app.post("/auth/register", response_model=TokenOut, status_code=201, tags=["Auth"])
def register(payload: RegisterInput, db: Session = Depends(get_db)):
    user = User(username=payload.username.lower(), email=payload.email.lower(), hashed_password=hash_password(payload.password), role=Role.EMPLOYEE)
    db.add(user)
    try:
        db.flush()
        db.add(Employee(user_id=user.id, full_name=payload.full_name, designation="Employee",
                        department="Unassigned", joining_date=date.today(), salary=0))
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username or email is already registered")
    return {"access_token": create_access_token(user), "user": user}


@app.post("/auth/login", response_model=TokenOut, tags=["Auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.username) == form_data.username.lower()))
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is inactive")
    return {"access_token": create_access_token(user), "user": user}


@app.get("/auth/me", response_model=UserOut, tags=["Auth"])
def me(user: User = Depends(get_current_user)):
    return user


@app.post("/auth/users", response_model=UserOut, status_code=201, tags=["Auth"])
def create_privileged_user(payload: AdminUserCreate, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    account = User(username=payload.username.lower(), email=payload.email.lower(),
                   hashed_password=hash_password(payload.password), role=payload.role)
    db.add(account)
    try:
        db.flush()
        if account.role == Role.EMPLOYEE:
            employee = Employee(user_id=account.id, full_name=account.username, designation="Employee",
                                department="Unassigned", joining_date=date.today(), salary=0)
            db.add(employee)
        db.commit()
        db.refresh(account)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username or email is already registered")
    return account


@app.get("/auth/users", response_model=list[UserOut], tags=["Auth"])
def list_users(user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.username)).all()


@app.patch("/auth/users/{user_id}", response_model=UserOut, tags=["Auth"])
def update_user(user_id: int, payload: AdminUserUpdate, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    account = db.get(User, user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="User not found")
    changes = payload.model_dump(exclude_unset=True)
    if account.id == user.id and changes.get("is_active") is False:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
    if account.role == Role.ADMIN and changes.get("role") not in (None, Role.ADMIN):
        active_admins = db.scalar(select(func.count(User.id)).where(User.role == Role.ADMIN, User.is_active.is_(True))) or 0
        if account.is_active and active_admins <= 1:
            raise HTTPException(status_code=409, detail="At least one active administrator must remain")
    for key, value in changes.items():
        setattr(account, key, value)
    if account.role == Role.EMPLOYEE and db.scalar(select(Employee.id).where(Employee.user_id == account.id)) is None:
        db.add(Employee(user_id=account.id, full_name=account.username, designation="Employee",
                        department="Unassigned", joining_date=date.today(), salary=0))
    db.commit()
    db.refresh(account)
    return account


@app.delete("/auth/users/{user_id}", status_code=204, tags=["Auth"])
def deactivate_user(user_id: int, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    account = db.get(User, user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="User not found")
    if account.id == user.id:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
    if account.role == Role.ADMIN and account.is_active:
        active_admins = db.scalar(select(func.count(User.id)).where(User.role == Role.ADMIN, User.is_active.is_(True))) or 0
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="At least one active administrator must remain")
    account.is_active = False
    db.commit()


@app.get("/employees", response_model=list[EmployeeOut], tags=["Employees"])
def list_employees(search: str | None = Query(default=None, max_length=160),
                   department: str | None = Query(default=None, max_length=120),
                   status_filter: EmployeeStatus | None = Query(default=None, alias="status"),
                   role_filter: Role | None = Query(default=None, alias="role"),
                   attendance_status: AttendanceStatus | None = None,
                   performance_min_rating: float | None = Query(default=None, ge=1, le=5),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Employee).join(User)
    if user.role == Role.EMPLOYEE:
        query = query.where(Employee.user_id == user.id)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(func.lower(Employee.full_name).like(term) | func.lower(Employee.designation).like(term)
                            | func.lower(Employee.department).like(term) | func.lower(User.username).like(term)
                            | func.lower(User.email).like(term))
    if department:
        query = query.where(func.lower(Employee.department) == department.lower())
    if status_filter:
        query = query.where(Employee.status == status_filter)
    if role_filter:
        query = query.where(User.role == role_filter)
    if attendance_status:
        attendance_match = select(Attendance.id).where(
            Attendance.employee_id == Employee.id, Attendance.date == date.today(),
        )
        if attendance_status == AttendanceStatus.LATE:
            attendance_match = attendance_match.where(
                (Attendance.status == AttendanceStatus.LATE) | Attendance.is_late.is_(True),
            )
        elif attendance_status == AttendanceStatus.PRESENT:
            attendance_match = attendance_match.where(
                Attendance.status == AttendanceStatus.PRESENT, Attendance.is_late.is_(False),
            )
        else:
            attendance_match = attendance_match.where(Attendance.status == attendance_status)
        query = query.where(attendance_match.exists())
    if performance_min_rating is not None:
        query = query.where(select(Performance.id).where(
            Performance.employee_id == Employee.id, Performance.rating >= performance_min_rating,
        ).exists())
    return [employee_out(row) for row in db.scalars(query.order_by(Employee.full_name)).all()]


@app.get("/shifts", response_model=list[ShiftOut], tags=["Shifts"])
def list_shifts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Shift).order_by(Shift.start_time)).all()


@app.post("/shifts", response_model=ShiftOut, status_code=201, tags=["Shifts"])
def create_shift(payload: ShiftCreate, user: User = Depends(require_roles(Role.HR, Role.ADMIN)),
                 db: Session = Depends(get_db)):
    shift = Shift(**payload.model_dump())
    db.add(shift)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A shift with this name already exists")
    db.refresh(shift)
    return shift


@app.get("/employee-shifts", response_model=list[EmployeeShiftOut], tags=["Shifts"])
def list_employee_shifts(employee_id: int | None = None, department: str | None = None,
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(EmployeeShift).join(Employee).join(User).join(Shift)
    if user.role == Role.EMPLOYEE:
        query = query.where(Employee.user_id == user.id)
    elif employee_id is not None:
        query = query.where(EmployeeShift.employee_id == employee_id)
    if department:
        query = query.where(func.lower(Employee.department) == department.lower())
    return [employee_shift_out(row) for row in db.scalars(query.order_by(Employee.full_name)).all()]


@app.post("/employee-shifts", response_model=EmployeeShiftOut, status_code=201, tags=["Shifts"])
def assign_employee_shift(payload: EmployeeShiftAssign, user: User = Depends(require_roles(Role.HR, Role.ADMIN)),
                          db: Session = Depends(get_db)):
    employee = db.get(Employee, payload.employee_id)
    shift = db.get(Shift, payload.shift_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if employee.status != EmployeeStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Inactive employees cannot be assigned a shift")
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    assignment = db.scalar(select(EmployeeShift).where(EmployeeShift.employee_id == employee.id))
    if assignment is None:
        assignment = EmployeeShift(employee_id=employee.id, shift_id=shift.id)
        db.add(assignment)
    else:
        assignment.shift_id = shift.id
        assignment.assigned_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An employee shift assignment already exists")
    db.refresh(assignment)
    return employee_shift_out(assignment)


@app.post("/employees", response_model=EmployeeOut, status_code=201, tags=["Employees"])
def create_employee(payload: EmployeeCreate, user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    account = User(username=payload.username.lower(), email=payload.email.lower(), hashed_password=hash_password(payload.password), role=Role.EMPLOYEE)
    db.add(account)
    try:
        db.flush()
        employee = Employee(user_id=account.id, full_name=payload.full_name, designation=payload.designation,
                            department=payload.department, joining_date=payload.joining_date, salary=payload.salary)
        db.add(employee)
        db.commit()
        db.refresh(employee)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username or email is already registered")
    return employee_out(employee)


@app.get("/employees/{employee_id}", response_model=EmployeeOut, tags=["Employees"])
def get_employee_profile(employee_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if user.role == Role.EMPLOYEE and employee.user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only view your own employee profile")
    return employee_out(employee)


@app.patch("/employees/{employee_id}", response_model=EmployeeOut, tags=["Employees"])
def update_employee(employee_id: int, payload: EmployeeUpdate, user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    for key, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(employee, key, value)
    db.commit()
    db.refresh(employee)
    return employee_out(employee)


@app.post("/attendance/check-in", response_model=AttendanceOut, status_code=201, tags=["Attendance"])
def check_in(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    employee = get_employee(db, user)
    if employee.status != EmployeeStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="Inactive employees cannot check in")
    today = date.today()
    row = db.scalar(select(Attendance).where(Attendance.employee_id == employee.id, Attendance.date == today))
    if row and row.check_in:
        raise HTTPException(status_code=409, detail="You have already checked in today")
    check_in_time = datetime.now(timezone.utc)
    assignment = db.scalar(select(EmployeeShift).where(EmployeeShift.employee_id == employee.id))
    is_late = is_late_check_in(check_in_time, assignment)
    is_early = is_early_check_in(check_in_time, assignment)
    scheduled_start = assignment.shift.start_time if assignment else settings.attendance_late_after
    if row is None:
        row = Attendance(employee_id=employee.id, date=today, status=AttendanceStatus.PRESENT,
                         check_in=check_in_time, is_late=is_late, is_early=is_early)
        db.add(row)
    else:
        row.check_in = check_in_time
        row.status = AttendanceStatus.PRESENT
        row.is_late = is_late
        row.is_early = is_early
    if is_late:
        notify(db, user.id, "Late attendance detected",
               f"Your check-in was after your scheduled start time of {scheduled_start.strftime('%H:%M')}.")
        notify_hr_users(db, "Late attendance alert",
                        f"{employee.full_name} checked in after the scheduled start time of {scheduled_start.strftime('%H:%M')}.")
    db.commit()
    db.refresh(row)
    return attendance_out(row)


@app.post("/attendance/check-out", response_model=AttendanceOut, tags=["Attendance"])
def check_out(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    employee = get_employee(db, user)
    row = db.scalar(select(Attendance).where(Attendance.employee_id == employee.id, Attendance.date == date.today()))
    if row is None or row.check_in is None:
        raise HTTPException(status_code=400, detail="Check in before checking out")
    if row.check_out:
        raise HTTPException(status_code=409, detail="You have already checked out today")
    row.check_out = datetime.now(timezone.utc)
    assignment = db.scalar(select(EmployeeShift).where(EmployeeShift.employee_id == employee.id))
    row.is_early_out = is_early_check_out(row.check_out, row.date, assignment)
    db.commit()
    db.refresh(row)
    return attendance_out(row)


@app.get("/attendance", response_model=list[AttendanceOut], tags=["Attendance"])
def list_attendance(employee_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    yesterday = date.today() - timedelta(days=1)
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    active_query = select(Employee).join(User).where(Employee.status == EmployeeStatus.ACTIVE, User.is_active.is_(True))
    if user.role == Role.EMPLOYEE:
        active_query = active_query.where(Employee.user_id == user.id)
    active_employees = db.scalars(active_query).all()
    for employee in active_employees:
        assignment = db.scalar(select(EmployeeShift).where(EmployeeShift.employee_id == employee.id))
        if assignment:
            overnight = assignment.shift.end_time <= assignment.shift.start_time
            shift_end_date = yesterday + timedelta(days=1 if overnight else 0)
            scheduled_end = datetime.combine(shift_end_date, assignment.shift.end_time).astimezone()
            if datetime.now().astimezone() < scheduled_end:
                continue
        existing = db.scalar(select(Attendance).where(Attendance.employee_id == employee.id, Attendance.date == yesterday))
        approved_leave = db.scalar(select(Leave.id).where(
            Leave.employee_id == employee.id, Leave.status == LeaveStatus.APPROVED,
            Leave.start_date <= yesterday, Leave.end_date >= yesterday,
        ))
        if existing is None and approved_leave is None:
            db.add(Attendance(employee_id=employee.id, date=yesterday, status=AttendanceStatus.ABSENT))
    db.commit()
    query = select(Attendance)
    if user.role == Role.EMPLOYEE:
        query = query.where(Attendance.employee_id == get_employee(db, user).id)
    elif employee_id:
        query = query.where(Attendance.employee_id == employee_id)
    return [attendance_out(row) for row in db.scalars(query.order_by(Attendance.date.desc(), Attendance.id.desc())).all()]


@app.post("/attendance/mark", response_model=AttendanceOut, status_code=201, tags=["Attendance"])
def mark_attendance(payload: AttendanceMark, user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    employee = db.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    row = db.scalar(select(Attendance).where(Attendance.employee_id == payload.employee_id, Attendance.date == payload.date))
    if row is None:
        row = Attendance(employee_id=payload.employee_id, date=payload.date, status=payload.status,
                         check_in=payload.check_in, check_out=payload.check_out)
        db.add(row)
    else:
        row.status, row.check_in, row.check_out = payload.status, payload.check_in, payload.check_out
    assignment = db.scalar(select(EmployeeShift).where(EmployeeShift.employee_id == employee.id))
    row.is_late = payload.status == AttendanceStatus.LATE or is_late_check_in(payload.check_in, assignment)
    row.is_early = is_early_check_in(payload.check_in, assignment)
    row.is_early_out = is_early_check_out(payload.check_out, payload.date, assignment)
    if payload.status in (AttendanceStatus.ABSENT, AttendanceStatus.HALF_DAY):
        notify(db, employee.user_id, "Attendance updated",
               f"Your attendance for {payload.date} was marked {payload.status.value.lower().replace('_', ' ')}.")
    db.commit()
    db.refresh(row)
    return attendance_out(row)


@app.get("/leaves", response_model=list[LeaveOut], tags=["Leaves"])
def list_leaves(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Leave)
    if user.role == Role.EMPLOYEE:
        query = query.where(Leave.employee_id == get_employee(db, user).id)
    return [leave_out(row) for row in db.scalars(query.order_by(Leave.created_at.desc())).all()]


@app.get("/leaves/calendar", tags=["Leaves"])
def leave_calendar(start_date: date | None = None, end_date: date | None = None, department: str | None = None,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start = start_date or date.today().replace(day=1)
    end = end_date or (start + timedelta(days=62))
    if end < start or (end - start).days > 366:
        raise HTTPException(status_code=422, detail="Calendar range must be valid and no longer than 367 days")
    query = select(Leave).join(Employee).where(
        Leave.status.in_([LeaveStatus.PENDING, LeaveStatus.APPROVED]),
        Leave.start_date <= end, Leave.end_date >= start,
    )
    if user.role == Role.EMPLOYEE:
        query = query.where(Employee.user_id == user.id)
    if department:
        query = query.where(func.lower(Employee.department) == department.lower())
    rows = db.scalars(query.order_by(Leave.start_date, Employee.full_name)).all()
    return [leave_out(row) for row in rows]


@app.post("/leaves", response_model=LeaveOut, status_code=201, tags=["Leaves"])
def apply_leave(payload: LeaveCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    employee = get_employee(db, user)
    if employee.status != EmployeeStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="Inactive employees cannot apply for leave")
    ensure_default_leave_policies(db)
    ensure_leave_balances(db, employee.id)
    requested_days = leave_days(payload.start_date, payload.end_date)
    balance = db.scalar(select(LeaveBalance).where(
        LeaveBalance.employee_id == employee.id, LeaveBalance.leave_type == payload.leave_type,
    ))
    if balance is None:
        raise HTTPException(status_code=409, detail="No leave policy is configured for this leave type")
    pending_days = sum(
        leave_days(row.start_date, row.end_date)
        for row in db.scalars(select(Leave).where(
            Leave.employee_id == employee.id, Leave.leave_type == payload.leave_type,
            Leave.status == LeaveStatus.PENDING,
        )).all()
    )
    if requested_days + pending_days > balance.remaining_days:
        raise HTTPException(status_code=409, detail="Requested leave exceeds your available balance")
    overlap = db.scalar(select(Leave.id).where(
        Leave.employee_id == employee.id,
        Leave.status.in_([LeaveStatus.PENDING, LeaveStatus.APPROVED]),
        Leave.start_date <= payload.end_date, Leave.end_date >= payload.start_date,
    ))
    if overlap is not None:
        raise HTTPException(status_code=409, detail="This request overlaps an existing leave request")
    row = Leave(employee_id=employee.id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return leave_out(row)


@app.patch("/leaves/{leave_id}", response_model=LeaveOut, tags=["Leaves"])
def review_leave(leave_id: int, payload: LeaveReview, user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    row = db.get(Leave, leave_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if row.status != LeaveStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending leave requests can be reviewed")
    if payload.status == LeaveStatus.APPROVED:
        ensure_leave_balances(db, row.employee_id)
        days = leave_days(row.start_date, row.end_date)
        result = db.execute(
            update(LeaveBalance)
            .where(
                LeaveBalance.employee_id == row.employee_id,
                LeaveBalance.leave_type == row.leave_type,
                LeaveBalance.remaining_days >= days,
            )
            .values(remaining_days=LeaveBalance.remaining_days - days)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Insufficient leave balance to approve this request")
    row.status = payload.status
    notify(db, row.employee.user_id, f"Leave {payload.status.value.lower()}",
           f"Your {row.leave_type.value.lower()} leave request from {row.start_date} to {row.end_date} was {payload.status.value.lower()}.")
    db.commit()
    db.refresh(row)
    return leave_out(row)


@app.get("/documents", response_model=list[DocumentOut], tags=["Documents"])
def list_documents(employee_id: int | None = None, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    query = select(Document).join(Employee)
    if user.role == Role.EMPLOYEE:
        query = query.where(Employee.user_id == user.id)
    elif employee_id is not None:
        query = query.where(Document.employee_id == employee_id)
    return [document_out(row) for row in db.scalars(query.order_by(Document.uploaded_at.desc())).all()]


@app.post("/documents", response_model=DocumentOut, status_code=201, tags=["Documents"])
def upload_document(file: UploadFile = File(...), employee_id: int | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == Role.EMPLOYEE:
        employee = get_employee(db, user)
        if employee_id is not None and employee_id != employee.id:
            raise HTTPException(status_code=403, detail="You can only upload documents to your own profile")
    else:
        if employee_id is None:
            raise HTTPException(status_code=422, detail="employee_id is required for HR and administrators")
        employee = db.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(status_code=404, detail="Employee not found")

    original_name = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    extension = Path(original_name).suffix.lower()
    supported_types = {
        ".pdf": {"application/pdf", "application/octet-stream"},
        ".png": {"image/png", "application/octet-stream"},
        ".jpg": {"image/jpeg", "application/octet-stream"},
        ".jpeg": {"image/jpeg", "application/octet-stream"},
        ".doc": {"application/msword", "application/octet-stream"},
        ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/octet-stream"},
    }
    if not original_name or len(original_name) > 255 or extension not in supported_types:
        raise HTTPException(status_code=415, detail="Upload a PDF, DOC, DOCX, PNG, or JPG document")
    if file.content_type and file.content_type.lower() not in supported_types[extension]:
        raise HTTPException(status_code=415, detail="The uploaded file type does not match its extension")
    content = file.file.read(settings.document_max_size_bytes + 1)
    if len(content) > settings.document_max_size_bytes:
        raise HTTPException(status_code=413, detail="Document exceeds the configured upload size limit")
    stored_name = f"{uuid4().hex}{extension}"
    storage_dir = Path(settings.document_storage_dir).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / stored_name
    with stored_path.open("xb") as stored_file:
        stored_file.write(content)
    document = Document(employee_id=employee.id, file_name=original_name, file_url=stored_name)
    db.add(document)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        stored_path.unlink(missing_ok=True)
        raise
    db.refresh(document)
    return document_out(document)


@app.get("/documents/{document_id}/download", tags=["Documents"])
def download_document(document_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if user.role == Role.EMPLOYEE and document.employee.user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only access your own documents")
    stored_name = Path(document.file_url).name
    stored_path = Path(settings.document_storage_dir).resolve() / stored_name
    if not stored_path.is_file():
        raise HTTPException(status_code=404, detail="Document file is unavailable")
    return FileResponse(stored_path, media_type="application/octet-stream", filename=document.file_name)


@app.get("/performance", response_model=list[PerformanceOut], tags=["Performance"])
def list_performance(employee_id: int | None = None, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    query = select(Performance).join(Employee)
    if user.role == Role.EMPLOYEE:
        query = query.where(Employee.user_id == user.id)
    elif employee_id is not None:
        query = query.where(Performance.employee_id == employee_id)
    return [performance_out(row) for row in db.scalars(query.order_by(Performance.created_at.desc())).all()]


@app.post("/performance", response_model=PerformanceOut, status_code=201, tags=["Performance"])
def create_performance_review(payload: PerformanceCreate, user: User = Depends(require_roles(Role.HR, Role.ADMIN)),
                              db: Session = Depends(get_db)):
    if db.get(Employee, payload.employee_id) is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    row = Performance(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return performance_out(row)


@app.get("/reports/analytics", tags=["Reports"])
def advanced_analytics(start_date: date | None = None, end_date: date | None = None,
                       department: str | None = Query(default=None, max_length=120),
                       user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    start = start_date or date.today().replace(day=1)
    end = end_date or date.today()
    if end < start or (end - start).days > 3660:
        raise HTTPException(status_code=422, detail="Report range must be valid and no longer than ten years")
    attendance_query = select(
        Attendance.date, Attendance.status, Attendance.is_late, func.count(Attendance.id),
    ).join(Employee).where(Attendance.date >= start, Attendance.date <= end)
    leave_query = select(Leave.start_date, Leave.status).join(Employee).where(
        Leave.start_date <= end, Leave.end_date >= start,
    )
    performance_query = select(Employee.department, func.avg(Performance.rating), func.count(Performance.id)).join(
        Employee, Performance.employee_id == Employee.id,
    ).where(func.date(Performance.created_at) >= start.isoformat(),
            func.date(Performance.created_at) <= end.isoformat())
    employee_query = select(Employee.department, func.count(Employee.id))
    if department:
        attendance_query = attendance_query.where(func.lower(Employee.department) == department.lower())
        leave_query = leave_query.where(func.lower(Employee.department) == department.lower())
        performance_query = performance_query.where(func.lower(Employee.department) == department.lower())
        employee_query = employee_query.where(func.lower(Employee.department) == department.lower())
    attendance_rows = db.execute(attendance_query.group_by(Attendance.date, Attendance.status, Attendance.is_late)
                                 .order_by(Attendance.date)).all()
    attendance_counts: dict[tuple[date, AttendanceStatus], int] = {}
    for day, row_status, is_late, count in attendance_rows:
        state = AttendanceStatus.LATE if is_late else row_status
        key = (day, state)
        attendance_counts[key] = attendance_counts.get(key, 0) + count
    leave_counts: dict[tuple[str, LeaveStatus], int] = {}
    for leave_start, leave_status in db.execute(leave_query.order_by(Leave.start_date)).all():
        key = (leave_start.strftime("%Y-%m"), leave_status)
        leave_counts[key] = leave_counts.get(key, 0) + 1
    performance_rows = db.execute(performance_query.group_by(Employee.department)
                                  .order_by(Employee.department)).all()
    department_rows = db.execute(employee_query.group_by(Employee.department)
                                 .order_by(Employee.department)).all()
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "department": department,
        "attendance_trends": [
            {"date": day.isoformat(), "status": state.value, "count": count}
            for (day, state), count in sorted(attendance_counts.items(), key=lambda item: (item[0][0], item[0][1].value))
        ],
        "leave_trends": [
            {"month": month, "status": state.value, "count": count}
            for (month, state), count in sorted(leave_counts.items(), key=lambda item: (item[0][0], item[0][1].value))
        ],
        "performance_by_department": [
            {"department": dept, "average_rating": round(float(avg_rating or 0), 2), "reviews": count}
            for dept, avg_rating, count in performance_rows
        ],
        "employees_by_department": [
            {"department": dept, "employees": count} for dept, count in department_rows
        ],
    }


@app.get("/leave-policies", response_model=list[LeavePolicyOut], tags=["Leaves"])
def list_leave_policies(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_default_leave_policies(db)
    db.commit()
    return db.scalars(select(LeavePolicy).order_by(LeavePolicy.leave_type)).all()


@app.post("/leave-policies", response_model=LeavePolicyOut, status_code=201, tags=["Leaves"])
def create_leave_policy(payload: LeavePolicyCreate, user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    if db.scalar(select(LeavePolicy.id).where(LeavePolicy.leave_type == payload.leave_type)) is not None:
        raise HTTPException(status_code=409, detail="A policy already exists for this leave type")
    policy = LeavePolicy(**payload.model_dump())
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy


@app.patch("/leave-policies/{policy_id}", response_model=LeavePolicyOut, tags=["Leaves"])
def update_leave_policy(policy_id: int, payload: LeavePolicyUpdate, user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    policy = db.get(LeavePolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Leave policy not found")
    exceeds_balance = db.scalar(select(LeaveBalance.id).where(
        LeaveBalance.leave_type == policy.leave_type,
        LeaveBalance.remaining_days > payload.total_days_allowed,
    ))
    if exceeds_balance is not None:
        raise HTTPException(status_code=409, detail="The allowance cannot be lower than an existing employee balance")
    policy.total_days_allowed = payload.total_days_allowed
    db.commit()
    db.refresh(policy)
    return policy


@app.delete("/leave-policies/{policy_id}", status_code=204, tags=["Leaves"])
def delete_leave_policy(policy_id: int, user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    policy = db.get(LeavePolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Leave policy not found")
    in_use = db.scalar(select(LeaveBalance.id).where(LeaveBalance.leave_type == policy.leave_type))
    has_requests = db.scalar(select(Leave.id).where(Leave.leave_type == policy.leave_type))
    if in_use is not None or has_requests is not None:
        raise HTTPException(status_code=409, detail="A leave policy with employee balances cannot be deleted")
    db.delete(policy)
    db.commit()


@app.get("/leave-balances", response_model=list[LeaveBalanceOut], tags=["Leaves"])
def list_leave_balances(employee_id: int | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == Role.EMPLOYEE:
        employee = get_employee(db, user)
        employee_id = employee.id
    elif employee_id is None:
        raise HTTPException(status_code=422, detail="employee_id is required for HR and administrators")
    if db.get(Employee, employee_id) is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    ensure_default_leave_policies(db)
    ensure_leave_balances(db, employee_id)
    db.commit()
    rows = db.scalars(select(LeaveBalance).where(LeaveBalance.employee_id == employee_id)).all()
    policies = {policy.leave_type: policy.total_days_allowed for policy in db.scalars(select(LeavePolicy)).all()}
    return [
        {"id": row.id, "employee_id": row.employee_id, "leave_type": row.leave_type,
         "remaining_days": row.remaining_days, "total_days_allowed": policies.get(row.leave_type, row.remaining_days)}
        for row in rows
    ]


@app.get("/payroll", response_model=list[PayrollOut], tags=["Payroll"])
def list_payroll(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Payroll)
    if user.role == Role.EMPLOYEE:
        query = query.where(Payroll.employee_id == get_employee(db, user).id)
    return [payroll_out(row) for row in db.scalars(query.order_by(Payroll.month.desc())).all()]


@app.post("/payroll", response_model=PayrollOut, status_code=201, tags=["Payroll"])
def generate_payroll(payload: PayrollCreate, user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    employee = db.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if db.scalar(select(Payroll).where(Payroll.employee_id == payload.employee_id, Payroll.month == payload.month)):
        raise HTTPException(status_code=409, detail="Payroll already exists for this employee and month")
    row = Payroll(**payload.model_dump(), net_salary=round(payload.basic_salary + payload.allowances - payload.deductions + payload.bonus, 2))
    db.add(row)
    notify(db, employee.user_id, "Payroll generated", f"Your payslip for {payload.month} is ready.")
    db.commit()
    db.refresh(row)
    return payroll_out(row)


@app.get("/payroll/summary", tags=["Payroll"])
def payroll_summary(month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Payroll).where(Payroll.month == month)
    if user.role == Role.EMPLOYEE:
        query = query.where(Payroll.employee_id == get_employee(db, user).id)
    rows = db.scalars(query).all()
    return {
        "month": month,
        "employee_count": len({row.employee_id for row in rows}),
        "basic_salary": round(sum(row.basic_salary for row in rows), 2),
        "allowances": round(sum(row.allowances for row in rows), 2),
        "bonus": round(sum(row.bonus for row in rows), 2),
        "deductions": round(sum(row.deductions for row in rows), 2),
        "net_salary": round(sum(row.net_salary for row in rows), 2),
    }


@app.get("/notifications", response_model=list[NotificationOut], tags=["Notifications"])
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc())).all()


@app.patch("/notifications/{notification_id}/read", response_model=NotificationOut, tags=["Notifications"])
def read_notification(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    row.is_read = True
    db.commit()
    db.refresh(row)
    return row


@app.get("/dashboard", tags=["Dashboard"])
def dashboard(user: User = Depends(require_roles(Role.HR, Role.ADMIN)), db: Session = Depends(get_db)):
    today = date.today()
    month = today.strftime("%Y-%m")
    attendance_breakdown = {}
    for state in AttendanceStatus:
        state_filter = Attendance.status == state
        if state == AttendanceStatus.LATE:
            state_filter = (Attendance.status == state) | Attendance.is_late.is_(True)
        elif state == AttendanceStatus.PRESENT:
            state_filter = (Attendance.status == state) & Attendance.is_late.is_(False)
        attendance_breakdown[state.value] = db.scalar(select(func.count(Attendance.id)).where(
            Attendance.date == today, state_filter,
        )) or 0
    return {
        "total_employees": db.scalar(select(func.count(Employee.id)).where(Employee.status == EmployeeStatus.ACTIVE)) or 0,
        "present_today": db.scalar(select(func.count(Attendance.id)).where(Attendance.date == today, Attendance.status == AttendanceStatus.PRESENT)) or 0,
        "pending_leaves": db.scalar(select(func.count(Leave.id)).where(Leave.status == LeaveStatus.PENDING)) or 0,
        "payroll_this_month": db.scalar(select(func.coalesce(func.sum(Payroll.net_salary), 0)).where(Payroll.month == month)) or 0,
        "attendance_breakdown": attendance_breakdown,
        "leave_breakdown": {state.value: db.scalar(select(func.count(Leave.id)).where(Leave.status == state)) or 0 for state in LeaveStatus},
    }


@app.get("/admin/analytics", tags=["Dashboard"])
def admin_analytics(user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    today = date.today()
    return {
        "users_total": db.scalar(select(func.count(User.id))) or 0,
        "users_active": db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0,
        "users_by_role": {
            role.value: db.scalar(select(func.count(User.id)).where(User.role == role)) or 0
            for role in Role
        },
        "attendance_records": db.scalar(select(func.count(Attendance.id))) or 0,
        "leave_requests": db.scalar(select(func.count(Leave.id))) or 0,
        "payroll_records": db.scalar(select(func.count(Payroll.id))) or 0,
        "employees_active": db.scalar(select(func.count(Employee.id)).where(Employee.status == EmployeeStatus.ACTIVE)) or 0,
        "present_today": db.scalar(select(func.count(Attendance.id)).where(
            Attendance.date == today, Attendance.status.in_([AttendanceStatus.PRESENT, AttendanceStatus.LATE]),
        )) or 0,
    }


# ---------------- Phase 4: Employee experience & integrations ----------------
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from sqlalchemy import desc
import csv
import io
import smtplib
from email.message import EmailMessage
from .models import OnboardingStatus, ResignationStatus, InternalTaskStatus

class OnboardingCreateInput(BaseModel):
    employee_id: int = Field(gt=0)
    task_name: str = Field(min_length=2, max_length=180)
    due_date: date
class OnboardingStatusInput(BaseModel):
    status: OnboardingStatus
class ResignationCreateInput(BaseModel):
    reason: str = Field(min_length=5, max_length=5000)
    notice_period: int = Field(ge=0, le=365)
class ResignationReviewInput(BaseModel):
    status: ResignationStatus
class AnnouncementInput(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    message: str = Field(min_length=2, max_length=20000)
class TaskCreateInput(BaseModel):
    assigned_to: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=10000)
    due_date: date
class TaskStatusInput(BaseModel):
    status: InternalTaskStatus
class FeedbackInput(BaseModel):
    message: str = Field(min_length=3, max_length=5000)
    rating: int = Field(ge=1, le=5)
class ProfileUpdateInput(BaseModel):
    email: str | None = Field(default=None, max_length=255)
class PasswordChangeInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
class PreferencesInput(BaseModel):
    email_enabled: bool = False
    announcements_enabled: bool = True
    task_reminders_enabled: bool = True

def phase4_employee(db: Session, user: User, required: bool = True):
    employee = db.query(Employee).filter(Employee.user_id == user.id).first()
    if employee is None and required:
        raise HTTPException(status_code=400, detail="Your account is not linked to an employee record")
    return employee

def phase4_dict(obj):
    result = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    for k, v in result.items():
        if isinstance(v, (date, datetime)): result[k] = v.isoformat()
        elif hasattr(v, "value"): result[k] = v.value
    return result

@app.post("/onboarding", status_code=201, tags=["Onboarding"])
def create_onboarding(payload: OnboardingCreateInput, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.HR, Role.ADMIN))):
    if not db.get(Employee, payload.employee_id): raise HTTPException(404, "Employee not found")
    item = Onboarding(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return phase4_dict(item)

@app.get("/onboarding", tags=["Onboarding"])
def list_onboarding(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    employee = phase4_employee(db, user, required=False)
    q = db.query(Onboarding)
    if user.role == Role.EMPLOYEE:
        if not employee: return []
        q = q.filter(Onboarding.employee_id == employee.id)
    return [phase4_dict(x) for x in q.order_by(Onboarding.due_date).all()]

@app.patch("/onboarding/{item_id}", tags=["Onboarding"])
def update_onboarding(item_id: int, payload: OnboardingStatusInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(Onboarding, item_id)
    if not item: raise HTTPException(404, "Onboarding task not found")
    employee = phase4_employee(db, user, required=False)
    if user.role == Role.EMPLOYEE and (not employee or item.employee_id != employee.id): raise HTTPException(403, "You can only update your own onboarding checklist")
    item.status = payload.status; db.commit(); db.refresh(item)
    return phase4_dict(item)

@app.post("/resignations", status_code=201, tags=["Resignations"])
def submit_resignation(payload: ResignationCreateInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    employee = phase4_employee(db, user)
    existing = db.query(Resignation).filter(Resignation.employee_id == employee.id, Resignation.status == ResignationStatus.PENDING).first()
    if existing: raise HTTPException(409, "You already have a pending resignation")
    item = Resignation(employee_id=employee.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return phase4_dict(item)

@app.get("/resignations", tags=["Resignations"])
def list_resignations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Resignation)
    employee = phase4_employee(db, user, required=False)
    if user.role == Role.EMPLOYEE:
        if not employee: return []
        q = q.filter(Resignation.employee_id == employee.id)
    return [phase4_dict(x) for x in q.order_by(desc(Resignation.created_at)).all()]

@app.patch("/resignations/{item_id}", tags=["Resignations"])
def review_resignation(item_id: int, payload: ResignationReviewInput, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.HR, Role.ADMIN))):
    item = db.get(Resignation, item_id)
    if not item: raise HTTPException(404, "Resignation not found")
    if item.status != ResignationStatus.PENDING: raise HTTPException(400, "Only pending resignations can be reviewed")
    item.status = payload.status; db.commit(); db.refresh(item)
    return phase4_dict(item)

@app.post("/announcements", status_code=201, tags=["Announcements"])
def create_announcement(payload: AnnouncementInput, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.HR, Role.ADMIN))):
    item = Announcement(**payload.model_dump(), created_by=user.id)
    db.add(item); db.commit(); db.refresh(item)
    return phase4_dict(item)

@app.get("/announcements", tags=["Announcements"])
def list_announcements(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [phase4_dict(x) for x in db.query(Announcement).order_by(desc(Announcement.created_at)).all()]

@app.get("/announcements/{item_id}", tags=["Announcements"])
def get_announcement(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(Announcement, item_id)
    if not item: raise HTTPException(404, "Announcement not found")
    return phase4_dict(item)

@app.post("/tasks", status_code=201, tags=["Tasks"])
def create_internal_task(payload: TaskCreateInput, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.HR, Role.ADMIN))):
    if not db.get(Employee, payload.assigned_to): raise HTTPException(404, "Employee not found")
    item = InternalTask(**payload.model_dump(), created_by=user.id)
    db.add(item); db.commit(); db.refresh(item)
    return phase4_dict(item)

@app.get("/tasks", tags=["Tasks"])
def list_internal_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(InternalTask)
    employee = phase4_employee(db, user, required=False)
    if user.role == Role.EMPLOYEE:
        if not employee: return []
        q = q.filter(InternalTask.assigned_to == employee.id)
    return [phase4_dict(x) for x in q.order_by(InternalTask.due_date).all()]

@app.patch("/tasks/{item_id}", tags=["Tasks"])
def update_internal_task(item_id: int, payload: TaskStatusInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(InternalTask, item_id)
    if not item: raise HTTPException(404, "Task not found")
    employee = phase4_employee(db, user, required=False)
    if user.role == Role.EMPLOYEE and (not employee or item.assigned_to != employee.id): raise HTTPException(403, "You can only update your own tasks")
    item.status = payload.status; db.commit(); db.refresh(item)
    return phase4_dict(item)

@app.post("/feedback", status_code=201, tags=["Feedback"])
def submit_feedback(payload: FeedbackInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    employee = phase4_employee(db, user)
    item = Feedback(employee_id=employee.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return phase4_dict(item)

@app.get("/feedback", tags=["Feedback"])
def list_feedback(db: Session = Depends(get_db), user: User = Depends(require_roles(Role.HR, Role.ADMIN))):
    return [phase4_dict(x) for x in db.query(Feedback).order_by(desc(Feedback.created_at)).all()]

@app.get("/profile/settings", tags=["Profile & Settings"])
def get_profile_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pref = db.query(NotificationPreference).filter_by(user_id=user.id).first()
    employee = phase4_employee(db, user, required=False)
    return {"user": {"id": user.id, "username": user.username, "email": user.email, "role": user.role.value},
            "employee": ({"id": employee.id, "full_name": employee.full_name, "designation": employee.designation, "department": employee.department} if employee else None),
            "preferences": phase4_dict(pref) if pref else {"email_enabled": False, "announcements_enabled": True, "task_reminders_enabled": True}}

@app.patch("/profile/settings", tags=["Profile & Settings"])
def update_profile_settings(payload: ProfileUpdateInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if payload.email is not None:
        from pydantic import TypeAdapter, EmailStr
        try: TypeAdapter(EmailStr).validate_python(payload.email)
        except Exception: raise HTTPException(422, "A valid email address is required")
        duplicate = db.query(User).filter(User.email == payload.email, User.id != user.id).first()
        if duplicate: raise HTTPException(409, "Email is already in use")
        user.email = payload.email
    db.commit(); db.refresh(user)
    return {"id": user.id, "username": user.username, "email": user.email, "role": user.role.value}

@app.post("/profile/change-password", tags=["Profile & Settings"])
def change_password(payload: PasswordChangeInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(payload.current_password, user.hashed_password): raise HTTPException(400, "Current password is incorrect")
    user.hashed_password = hash_password(payload.new_password); db.commit()
    return {"message": "Password changed successfully"}

@app.put("/profile/preferences", tags=["Profile & Settings"])
def save_preferences(payload: PreferencesInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pref = db.query(NotificationPreference).filter_by(user_id=user.id).first()
    if not pref:
        pref = NotificationPreference(user_id=user.id); db.add(pref)
    for key, value in payload.model_dump().items(): setattr(pref, key, value)
    db.commit(); db.refresh(pref)
    return phase4_dict(pref)

@app.get("/integrations/export/{resource}", tags=["Integrations"])
def export_resource(resource: str, format: str = Query("csv", pattern="^(csv|ics|pdf)$"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if format == "ics":
        if resource != "calendar": raise HTTPException(400, "ICS export is only available for calendar")
        rows = db.query(Leave).filter(Leave.status == LeaveStatus.APPROVED).all()
        employee = phase4_employee(db, user, required=False)
        if user.role == Role.EMPLOYEE: rows = [x for x in rows if employee and x.employee_id == employee.id]
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//WorkSphere HRMS//EN"]
        for row in rows:
            lines += ["BEGIN:VEVENT", f"UID:leave-{row.id}@worksphere", f"DTSTART;VALUE=DATE:{row.start_date.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(row.end_date + timedelta(days=1)).strftime('%Y%m%d')}", "SUMMARY:Approved leave", "END:VEVENT"]
        lines.append("END:VCALENDAR")
        return StreamingResponse(iter(["\\r\\n".join(lines)]), media_type="text/calendar", headers={"Content-Disposition": 'attachment; filename="worksphere-calendar.ics"'})
    mapping = {"onboarding": Onboarding, "resignations": Resignation, "announcements": Announcement, "tasks": InternalTask, "feedback": Feedback, "employees": Employee, "attendance": Attendance, "leaves": Leave, "payroll": Payroll}
    if resource not in mapping: raise HTTPException(404, "Unsupported export resource")
    if resource in {"feedback", "payroll", "employees", "attendance", "leaves"} and user.role == Role.EMPLOYEE:
        raise HTTPException(403, "HR/Admin permission required for this export")
    rows = db.query(mapping[resource]).all()
    if user.role == Role.EMPLOYEE and resource in {"onboarding", "resignations", "tasks"}:
        employee = phase4_employee(db, user, required=False)
        if not employee:
            rows = []
        elif resource == "onboarding":
            rows = [x for x in rows if x.employee_id == employee.id]
        elif resource == "resignations":
            rows = [x for x in rows if x.employee_id == employee.id]
        else:
            rows = [x for x in rows if x.assigned_to == employee.id]
    fieldnames = [c.name for c in rows[0].__table__.columns] if rows else ["message"]
    records = [{k: (v.value if hasattr(v, "value") else v.isoformat() if isinstance(v, (date, datetime)) else v) for k,v in phase4_dict(row).items()} for row in rows]
    if format == "pdf":
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import landscape, A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        except ImportError:
            raise HTTPException(503, "PDF export requires reportlab. Install it with: pip install reportlab")
        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=landscape(A4), title=f"WorkSphere {resource} report")
        styles = getSampleStyleSheet()
        story = [Paragraph(f"WorkSphere HRMS — {resource.title()} report", styles["Title"]), Spacer(1, 12)]
        table_data = [[str(k).replace("_", " ").title() for k in fieldnames]]
        for record in records:
            table_data.append([str(record.get(k, ""))[:120] for k in fieldnames])
        if len(table_data) == 1: table_data.append(["No records found"] + [""] * (len(fieldnames)-1))
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#26324a")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.4,colors.grey),("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f2f5f9")])]))
        story.append(table); doc.build(story)
        output.seek(0)
        return StreamingResponse(output, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="worksphere-{resource}.pdf"'})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames); writer.writeheader()
    for record in records: writer.writerow(record)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="worksphere-{resource}.csv"'})

@app.post("/integrations/email-test", tags=["Integrations"])
def send_test_email(to_email: str = Query(..., min_length=5, max_length=255), user: User = Depends(require_roles(Role.HR, Role.ADMIN))):
    host = os.getenv("SMTP_HOST"); sender = os.getenv("SMTP_FROM"); password = os.getenv("SMTP_PASSWORD")
    if not host or not sender or not password: raise HTTPException(503, "Email integration is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_FROM and SMTP_PASSWORD.")
    message = EmailMessage(); message["Subject"] = "WorkSphere HRMS email integration test"; message["From"] = sender; message["To"] = to_email
    message.set_content("This is a test email from WorkSphere HRMS.")
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as server:
            server.starttls(); server.login(sender, password); server.send_message(message)
    except Exception: raise HTTPException(502, "Email delivery failed; check SMTP configuration.")
    return {"message": "Test email sent"}
