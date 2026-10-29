from datetime import date, datetime, time, timezone
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text, Time as SQLTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    HR = "HR"
    ADMIN = "ADMIN"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    HALF_DAY = "HALF_DAY"
    LATE = "LATE"


class LeaveType(str, Enum):
    SICK = "SICK"
    CASUAL = "CASUAL"
    PAID = "PAID"


class LeaveStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SqlEnum(Role), default=Role.EMPLOYEE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    employee: Mapped["Employee | None"] = relationship(back_populates="user", uselist=False)


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    full_name: Mapped[str] = mapped_column(String(160))
    designation: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(120), index=True)
    joining_date: Mapped[date] = mapped_column(Date)
    salary: Mapped[float] = mapped_column(Float)
    status: Mapped[EmployeeStatus] = mapped_column(SqlEnum(EmployeeStatus), default=EmployeeStatus.ACTIVE)
    user: Mapped[User] = relationship(back_populates="employee")
    attendance: Mapped[list["Attendance"]] = relationship(back_populates="employee")
    leaves: Mapped[list["Leave"]] = relationship(back_populates="employee")
    payroll: Mapped[list["Payroll"]] = relationship(back_populates="employee")


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("employee_id", "date", name="uq_attendance_employee_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[AttendanceStatus] = mapped_column(SqlEnum(AttendanceStatus), default=AttendanceStatus.PRESENT)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_early: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_early_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    employee: Mapped[Employee] = relationship(back_populates="attendance")


class Leave(Base):
    __tablename__ = "leaves"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    leave_type: Mapped[LeaveType] = mapped_column(SqlEnum(LeaveType))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[LeaveStatus] = mapped_column(SqlEnum(LeaveStatus), default=LeaveStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    employee: Mapped[Employee] = relationship(back_populates="leaves")


class LeavePolicy(Base):
    __tablename__ = "leave_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    leave_type: Mapped[LeaveType] = mapped_column(SqlEnum(LeaveType), unique=True, index=True)
    total_days_allowed: Mapped[int] = mapped_column(Integer)


class LeaveBalance(Base):
    __tablename__ = "leave_balance"
    __table_args__ = (UniqueConstraint("employee_id", "leave_type", name="uq_leave_balance_employee_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    leave_type: Mapped[LeaveType] = mapped_column(SqlEnum(LeaveType))
    remaining_days: Mapped[int] = mapped_column(Integer)


class Payroll(Base):
    __tablename__ = "payroll"
    __table_args__ = (UniqueConstraint("employee_id", "month", name="uq_payroll_employee_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    basic_salary: Mapped[float] = mapped_column(Float)
    allowances: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    deductions: Mapped[float] = mapped_column(Float, default=0)
    bonus: Mapped[float] = mapped_column(Float, default=0)
    net_salary: Mapped[float] = mapped_column(Float)
    month: Mapped[str] = mapped_column(String(7), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    employee: Mapped[Employee] = relationship(back_populates="payroll")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    start_time: Mapped[time] = mapped_column(SQLTime)
    end_time: Mapped[time] = mapped_column(SQLTime)
    employee_shifts: Mapped[list["EmployeeShift"]] = relationship(back_populates="shift")


class EmployeeShift(Base):
    __tablename__ = "employee_shifts"
    __table_args__ = (UniqueConstraint("employee_id", name="uq_employee_shift_employee"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    employee: Mapped[Employee] = relationship()
    shift: Mapped[Shift] = relationship(back_populates="employee_shifts")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_url: Mapped[str] = mapped_column(String(255), unique=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    employee: Mapped[Employee] = relationship()


class Performance(Base):
    __tablename__ = "performance"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    review_period: Mapped[str] = mapped_column(String(80), index=True)
    rating: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    employee: Mapped[Employee] = relationship()


# Phase 4: employee experience and integrations
class OnboardingStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"

class Onboarding(Base):
    __tablename__ = "onboarding"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    task_name: Mapped[str] = mapped_column(String(180))
    status: Mapped[OnboardingStatus] = mapped_column(SqlEnum(OnboardingStatus), default=OnboardingStatus.PENDING)
    due_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class ResignationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

class Resignation(Base):
    __tablename__ = "resignations"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    notice_period: Mapped[int] = mapped_column(Integer)
    status: Mapped[ResignationStatus] = mapped_column(SqlEnum(ResignationStatus), default=ResignationStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Announcement(Base):
    __tablename__ = "announcements"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(180))
    message: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class InternalTaskStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"

class InternalTask(Base):
    __tablename__ = "internal_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    assigned_to: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[InternalTaskStatus] = mapped_column(SqlEnum(InternalTaskStatus), default=InternalTaskStatus.PENDING)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    rating: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    announcements_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    task_reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
