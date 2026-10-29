from datetime import date, datetime, time

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import AttendanceStatus, EmployeeStatus, LeaveStatus, LeaveType, Role


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterInput(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=160)


class LoginInput(BaseModel):
    username: str
    password: str


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role


class UserOut(ORMModel):
    id: int
    username: str
    email: EmailStr
    role: Role
    is_active: bool


class AdminUserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_update(self):
        if self.role is None and self.is_active is None:
            raise ValueError("At least one user field must be provided")
        return self


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class EmployeeCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=160)
    designation: str = Field(min_length=1, max_length=120)
    department: str = Field(min_length=1, max_length=120)
    joining_date: date
    salary: float = Field(ge=0)


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    designation: str | None = Field(default=None, min_length=1, max_length=120)
    department: str | None = Field(default=None, min_length=1, max_length=120)
    joining_date: date | None = None
    salary: float | None = Field(default=None, ge=0)
    status: EmployeeStatus | None = None


class EmployeeOut(ORMModel):
    id: int
    user_id: int
    full_name: str
    designation: str
    department: str
    joining_date: date
    salary: float
    status: EmployeeStatus
    username: str = ""
    email: EmailStr = ""
    role: Role = Role.EMPLOYEE


class AttendanceMark(BaseModel):
    employee_id: int
    date: date
    status: AttendanceStatus
    check_in: datetime | None = None
    check_out: datetime | None = None


class AttendanceOut(ORMModel):
    id: int
    employee_id: int
    check_in: datetime | None
    check_out: datetime | None
    date: date
    status: AttendanceStatus
    is_late: bool = False
    is_early: bool = False
    is_early_out: bool = False
    working_hours: float = 0
    employee_name: str = ""


class LeaveCreate(BaseModel):
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class LeaveReview(BaseModel):
    status: Literal[LeaveStatus.APPROVED, LeaveStatus.REJECTED]


class LeaveOut(ORMModel):
    id: int
    employee_id: int
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str
    status: LeaveStatus
    created_at: datetime
    employee_name: str = ""


class LeavePolicyCreate(BaseModel):
    leave_type: LeaveType
    total_days_allowed: int = Field(ge=0, le=365)


class LeavePolicyUpdate(BaseModel):
    total_days_allowed: int = Field(ge=0, le=365)


class LeavePolicyOut(ORMModel):
    id: int
    leave_type: LeaveType
    total_days_allowed: int


class LeaveBalanceOut(ORMModel):
    id: int
    employee_id: int
    leave_type: LeaveType
    remaining_days: int
    total_days_allowed: int


class PayrollCreate(BaseModel):
    employee_id: int
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    basic_salary: float = Field(ge=0)
    allowances: float = Field(default=0, ge=0)
    deductions: float = Field(default=0, ge=0)
    bonus: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def deductions_within_gross_pay(self):
        if self.deductions > self.basic_salary + self.allowances + self.bonus:
            raise ValueError("deductions cannot exceed gross pay")
        return self


class PayrollOut(ORMModel):
    id: int
    employee_id: int
    basic_salary: float
    allowances: float
    deductions: float
    bonus: float
    net_salary: float
    month: str
    created_at: datetime
    employee_name: str = ""


class NotificationOut(ORMModel):
    id: int
    title: str
    message: str
    is_read: bool
    created_at: datetime


class ShiftCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def different_shift_times(self):
        if self.start_time == self.end_time:
            raise ValueError("start_time and end_time must differ")
        return self


class ShiftOut(ORMModel):
    id: int
    name: str
    start_time: time
    end_time: time


class EmployeeShiftAssign(BaseModel):
    employee_id: int
    shift_id: int


class EmployeeShiftOut(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    department: str
    shift_id: int
    shift_name: str
    start_time: time
    end_time: time


class DocumentOut(ORMModel):
    id: int
    employee_id: int
    employee_name: str
    file_name: str
    file_url: str
    uploaded_at: datetime


class PerformanceCreate(BaseModel):
    employee_id: int
    review_period: str = Field(min_length=1, max_length=80)
    rating: float = Field(ge=1, le=5)
    feedback: str = Field(min_length=1, max_length=5000)


class PerformanceOut(ORMModel):
    id: int
    employee_id: int
    employee_name: str
    review_period: str
    rating: float
    feedback: str
    created_at: datetime
