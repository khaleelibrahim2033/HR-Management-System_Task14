import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarDays, Clock3, Download, FileText, Star, Users } from "lucide-react";
import { downloadFile, request } from "./api";

const today = new Date();
const isoDate = (value) => {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};
const dateLabel = (value) => value ? new Date(`${value.slice(0, 10)}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—";
const isHR = (user) => user.role !== "EMPLOYEE";

export function ShiftManagement({ user, refreshKey, onError, flash }) {
  const [shifts, setShifts] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((key) => key + 1);
  const load = useCallback(() => {
    request("/shifts").then(setShifts).catch(onError);
    request("/employee-shifts").then(setAssignments).catch(onError);
    if (isHR(user)) request("/employees").then(setEmployees).catch(onError);
  }, [user, refreshKey, reloadKey, onError]);
  useEffect(() => { load(); }, [load]);
  const createShift = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await request("/shifts", { method: "POST", body: JSON.stringify(values) });
      event.currentTarget.reset();
      flash("Shift created.");
      reload();
    } catch (err) { onError(err.message); }
  };
  const assignShift = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await request("/employee-shifts", { method: "POST", body: JSON.stringify({
        employee_id: Number(values.employee_id), shift_id: Number(values.shift_id),
      }) });
      flash("Employee shift assignment saved.");
      reload();
    } catch (err) { onError(err.message); }
  };
  return <div className="stack-layout">
    {isHR(user) && <section className="panel"><h3 className="phase-title">Create a shift</h3><form className="inline-form" onSubmit={createShift}>
      <label className="field">Shift name<input name="name" placeholder="Morning" minLength="2" maxLength="80" required /></label>
      <label className="field">Start time<input name="start_time" type="time" required /></label>
      <label className="field">End time<input name="end_time" type="time" required /></label>
      <button className="button button-primary">Add shift</button>
    </form></section>}
    {isHR(user) && <section className="panel"><h3 className="phase-title">Assign an employee</h3><form className="inline-form" onSubmit={assignShift}>
      <label className="field">Employee<select name="employee_id" required defaultValue=""><option value="" disabled>Select employee</option>{employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.full_name} · {employee.department}</option>)}</select></label>
      <label className="field">Shift<select name="shift_id" required defaultValue=""><option value="" disabled>Select shift</option>{shifts.map((shift) => <option key={shift.id} value={shift.id}>{shift.name} ({shift.start_time.slice(0, 5)}–{shift.end_time.slice(0, 5)})</option>)}</select></label>
      <button className="button button-primary" disabled={!shifts.length || !employees.length}>Save assignment</button>
    </form></section>}
    <section className="panel"><div className="panel-title"><div><h3>{isHR(user) ? "Shift schedule" : "Your shift"}</h3><p>Late arrivals are detected against the assigned shift start; early check-outs are flagged.</p></div></div>
      {assignments.length ? <div className="table-scroll"><table><thead><tr>{isHR(user) && <th>EMPLOYEE</th>}<th>DEPARTMENT</th><th>SHIFT</th><th>START</th><th>END</th></tr></thead><tbody>{assignments.map((item) => <tr key={item.id}>{isHR(user) && <td><strong>{item.employee_name}</strong></td>}<td>{item.department}</td><td>{item.shift_name}</td><td>{item.start_time.slice(0, 5)}</td><td>{item.end_time.slice(0, 5)}</td></tr>)}</tbody></table></div> : <div className="phase-empty"><Clock3 size={19} /><span>No shift assignments yet.</span></div>}
    </section>
    <section className="panel"><div className="panel-title"><div><h3>Available shifts</h3><p>Configured shift hours</p></div></div>{shifts.length ? <div className="phase-card-grid">{shifts.map((shift) => <div className="phase-info-card" key={shift.id}><span className="phase-icon"><Clock3 size={17} /></span><strong>{shift.name}</strong><span>{shift.start_time.slice(0, 5)} – {shift.end_time.slice(0, 5)}</span></div>)}</div> : <div className="phase-empty"><span>No shifts configured.</span></div>}</section>
  </div>;
}

export function LeaveCalendar({ user, refreshKey, onError }) {
  const [month, setMonth] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [leaves, setLeaves] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [department, setDepartment] = useState("");
  const start = new Date(month.getFullYear(), month.getMonth(), 1);
  const end = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  const load = useCallback(() => {
    const params = new URLSearchParams({ start_date: isoDate(start), end_date: isoDate(end) });
    if (department) params.set("department", department);
    request(`/leaves/calendar?${params}`).then(setLeaves).catch(onError);
    request("/employees").then(setEmployees).catch(onError);
  }, [start.getTime(), end.getTime(), department, refreshKey, onError]);
  useEffect(() => { load(); }, [load]);
  const days = useMemo(() => {
    const cells = [];
    const offset = start.getDay();
    for (let i = 0; i < offset; i += 1) cells.push(null);
    for (let day = 1; day <= end.getDate(); day += 1) cells.push(new Date(month.getFullYear(), month.getMonth(), day));
    while (cells.length % 7) cells.push(null);
    return cells;
  }, [month.getTime()]);
  const leavesFor = (day) => leaves.filter((leave) => leave.start_date <= isoDate(day) && leave.end_date >= isoDate(day));
  return <div className="stack-layout">
    <section className="panel"><div className="calendar-toolbar"><div><h3>{month.toLocaleDateString("en-US", { month: "long", year: "numeric" })}</h3><p>Approved and pending team time off</p></div><div className="calendar-controls">
      {isHR(user) && <input aria-label="Filter by department" placeholder="Department" value={department} onChange={(event) => setDepartment(event.target.value)} />}
      <button className="button button-quiet" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>Previous</button>
      <button className="button button-quiet" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>Next</button>
    </div></div>
      <div className="leave-calendar-grid">{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => <div className="calendar-weekday" key={day}>{day}</div>)}
        {days.map((day, index) => {
          if (!day) return <div className="calendar-day calendar-day-empty" key={`empty-${index}`} />;
          const away = leavesFor(day);
          return <div className={`calendar-day ${isoDate(day) === isoDate(today) ? "calendar-today" : ""}`} key={isoDate(day)}>
            <span className="calendar-day-number">{day.getDate()}</span>
            {away.slice(0, 3).map((leave) => <span className={`calendar-leave ${leave.status === "PENDING" ? "calendar-pending" : ""}`} title={`${leave.employee_name}: ${leave.leave_type}`} key={`${leave.id}-${isoDate(day)}`}>{leave.employee_name}</span>)}
            {away.length > 3 && <small className="calendar-more">+{away.length - 3} more</small>}
          </div>;
        })}
      </div>
    </section>
    <section className="panel"><div className="panel-title"><div><h3>Team availability</h3><p>{employees.length} {isHR(user) ? "employees" : "employee"} in the selected view · leave counts include pending requests</p></div><Users size={18} /></div>
      <div className="table-scroll"><table><thead><tr><th>DATE</th><th>EMPLOYEES AWAY</th><th>AVAILABLE</th><th>TEAM LEAVE</th></tr></thead><tbody>{Array.from({ length: end.getDate() }, (_, index) => {
        const day = new Date(month.getFullYear(), month.getMonth(), index + 1);
        const away = leavesFor(day);
        return <tr key={isoDate(day)}><td>{dateLabel(isoDate(day))}</td><td>{away.length}</td><td>{Math.max(0, employees.length - away.length)}</td><td>{away.length ? away.map((leave) => leave.employee_name).join(", ") : "—"}</td></tr>;
      })}</tbody></table></div>
    </section>
  </div>;
}

export function DocumentCenter({ user, refreshKey, onError, flash }) {
  const [documents, setDocuments] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [employeeId, setEmployeeId] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(() => {
    const params = employeeId ? `?employee_id=${encodeURIComponent(employeeId)}` : "";
    request(`/documents${params}`).then(setDocuments).catch(onError);
    if (isHR(user)) request("/employees").then(setEmployees).catch(onError);
  }, [user, employeeId, refreshKey, reloadKey, onError]);
  useEffect(() => { load(); }, [load]);
  const upload = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    const data = new FormData();
    data.append("file", file);
    const selectedEmployee = form.get("employee_id");
    const query = isHR(user) ? `?employee_id=${encodeURIComponent(selectedEmployee)}` : "";
    try {
      await request(`/documents${query}`, { method: "POST", body: data });
      event.currentTarget.reset();
      flash("Document uploaded securely.");
      setReloadKey((key) => key + 1);
    } catch (err) { onError(err.message); }
  };
  const openDocument = async (item) => {
    try { await downloadFile(item.file_url, item.file_name); } catch (err) { onError(err.message); }
  };
  return <div className="stack-layout">
    <section className="panel"><div className="panel-title"><div><h3>Upload a document</h3><p>PDF, DOC, DOCX, PNG, or JPG · maximum 10 MB</p></div><FileText size={18} /></div>
      <form className="inline-form document-form" onSubmit={upload}>
        {isHR(user) && <label className="field">Employee<select name="employee_id" required defaultValue=""><option value="" disabled>Select employee</option>{employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.full_name}</option>)}</select></label>}
        <label className="field">Choose file<input name="file" type="file" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg" required /></label>
        <button className="button button-primary" disabled={isHR(user) && !employees.length}>Upload document</button>
      </form>
    </section>
    <section className="panel"><div className="table-toolbar"><div><strong>{isHR(user) ? "Employee documents" : "Your documents"}</strong><small>Downloads require an authenticated account with access</small></div>{isHR(user) && <select className="status-filter" value={employeeId} onChange={(event) => setEmployeeId(event.target.value)}><option value="">All employees</option>{employees.map((employee) => <option value={employee.id} key={employee.id}>{employee.full_name}</option>)}</select>}</div>
      {documents.length ? <div className="table-scroll"><table><thead><tr>{isHR(user) && <th>EMPLOYEE</th>}<th>DOCUMENT</th><th>UPLOADED</th><th /></tr></thead><tbody>{documents.map((item) => <tr key={item.id}>{isHR(user) && <td>{item.employee_name}</td>}<td><FileText size={15} className="table-inline-icon" />{item.file_name}</td><td>{new Date(item.uploaded_at).toLocaleDateString()}</td><td><button className="text-button download-button" onClick={() => openDocument(item)}><Download size={14} /> Download</button></td></tr>)}</tbody></table></div> : <div className="phase-empty">No documents uploaded yet.</div>}
    </section>
  </div>;
}

export function PerformanceReviews({ user, refreshKey, onError, flash }) {
  const [reviews, setReviews] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [reloadKey, setReloadKey] = useState(0);
  const load = useCallback(() => {
    request("/performance").then(setReviews).catch(onError);
    if (isHR(user)) request("/employees").then(setEmployees).catch(onError);
  }, [user, refreshKey, reloadKey, onError]);
  useEffect(() => { load(); }, [load]);
  const submit = async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await request("/performance", { method: "POST", body: JSON.stringify({
        ...values, employee_id: Number(values.employee_id), rating: Number(values.rating),
      }) });
      event.currentTarget.reset();
      flash("Performance review saved.");
      setReloadKey((key) => key + 1);
    } catch (err) { onError(err.message); }
  };
  const average = reviews.length ? (reviews.reduce((sum, item) => sum + item.rating, 0) / reviews.length).toFixed(1) : "—";
  return <div className="stack-layout">
    {isHR(user) && <section className="panel"><div className="panel-title"><div><h3>Write a performance review</h3><p>Ratings are from 1 (needs improvement) to 5 (excellent).</p></div><Star size={18} /></div><form className="inline-form review-form" onSubmit={submit}>
      <label className="field">Employee<select name="employee_id" required defaultValue=""><option value="" disabled>Select employee</option>{employees.map((employee) => <option key={employee.id} value={employee.id}>{employee.full_name}</option>)}</select></label>
      <label className="field">Review period<input name="review_period" placeholder="2026 Q3" maxLength="80" required /></label>
      <label className="field">Rating<select name="rating" required defaultValue=""><option value="" disabled>Select rating</option>{[1, 2, 3, 4, 5].map((rating) => <option key={rating} value={rating}>{rating} / 5</option>)}</select></label>
      <label className="field review-feedback">Feedback<textarea name="feedback" minLength="1" maxLength="5000" required placeholder="Share strengths, progress, and areas for growth." /></label>
      <button className="button button-primary" disabled={!employees.length}>Save review</button>
    </form></section>}
    <div className="kpi-grid"><div className="kpi-card"><div className="kpi-icon purple"><Star size={18} /></div><span className="kpi-label">Average rating</span><strong className="kpi-value">{average}</strong><small>Across visible reviews</small></div><div className="kpi-card"><div className="kpi-icon blue"><FileText size={18} /></div><span className="kpi-label">Reviews recorded</span><strong className="kpi-value">{reviews.length}</strong><small>Feedback history</small></div></div>
    <section className="panel"><div className="panel-title"><div><h3>{isHR(user) ? "Review history" : "Your feedback history"}</h3><p>Ratings and written feedback by review period</p></div></div>
      {reviews.length ? <div className="review-list">{reviews.map((review) => <article className="review-card" key={review.id}><div className="review-card-heading"><div><strong>{isHR(user) ? review.employee_name : review.review_period}</strong><small>{isHR(user) ? review.review_period : `Added ${dateLabel(review.created_at)}`}</small></div><span className="rating-chip"><Star size={14} fill="currentColor" />{review.rating.toFixed(1)}</span></div><p>{review.feedback}</p></article>)}</div> : <div className="phase-empty">No reviews are available yet.</div>}
    </section>
  </div>;
}

export function ReportsDashboard({ refreshKey, onError }) {
  const [report, setReport] = useState(null);
  const [department, setDepartment] = useState("");
  const [dates, setDates] = useState(() => {
    const start = new Date(today.getFullYear(), today.getMonth(), 1);
    return { start_date: isoDate(start), end_date: isoDate(today) };
  });
  const [filters, setFilters] = useState(dates);
  const load = useCallback(() => {
    const params = new URLSearchParams({ ...filters });
    if (department) params.set("department", department);
    request(`/reports/analytics?${params}`).then(setReport).catch(onError);
  }, [filters, department, refreshKey, onError]);
  useEffect(() => { load(); }, [load]);
  const attendance = useMemo(() => {
    const totals = new Map();
    for (const item of report?.attendance_trends || []) {
      totals.set(item.date, (totals.get(item.date) || 0) + item.count);
    }
    return Array.from(totals, ([label, value]) => ({ label: dateLabel(label), value }));
  }, [report]);
  const leaveTotals = useMemo(() => {
    const totals = new Map();
    for (const item of report?.leave_trends || []) totals.set(item.month, (totals.get(item.month) || 0) + item.count);
    return Array.from(totals, ([label, value]) => ({ label, value }));
  }, [report]);
  const submitFilters = (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setFilters({ start_date: form.get("start_date"), end_date: form.get("end_date") });
    setDepartment(String(form.get("department") || "").trim());
  };
  return <div className="stack-layout">
    <section className="panel"><div className="panel-title"><div><h3>Report filters</h3><p>Select a date range and optional department.</p></div></div><form className="inline-form" onSubmit={submitFilters}>
      <label className="field">From<input type="date" name="start_date" defaultValue={dates.start_date} required /></label>
      <label className="field">To<input type="date" name="end_date" defaultValue={dates.end_date} required /></label>
      <label className="field">Department<input name="department" placeholder="All departments" defaultValue={department} /></label>
      <button className="button button-primary">Apply filters</button>
    </form></section>
    {report && <div className="reports-grid">
      <section className="panel"><div className="panel-title"><div><h3>Attendance trends</h3><p>Attendance records by day</p></div><Clock3 size={18} /></div><ReportBars rows={attendance} empty="No attendance records in this period." /></section>
      <section className="panel"><div className="panel-title"><div><h3>Leave trends</h3><p>Requests by month</p></div><CalendarDays size={18} /></div><ReportBars rows={leaveTotals} empty="No leave requests in this period." /></section>
      <section className="panel"><div className="panel-title"><div><h3>Performance insights</h3><p>Average rating by department</p></div><Star size={18} /></div>{report.performance_by_department.length ? <div className="table-scroll"><table><thead><tr><th>DEPARTMENT</th><th>AVG. RATING</th><th>REVIEWS</th></tr></thead><tbody>{report.performance_by_department.map((row) => <tr key={row.department}><td>{row.department}</td><td><span className="rating-chip"><Star size={13} fill="currentColor" />{row.average_rating}</span></td><td>{row.reviews}</td></tr>)}</tbody></table></div> : <div className="phase-empty">No performance reviews in this period.</div>}</section>
      <section className="panel"><div className="panel-title"><div><h3>Department headcount</h3><p>Employees by department</p></div><Users size={18} /></div><ReportBars rows={report.employees_by_department.map((row) => ({ label: row.department, value: row.employees }))} empty="No employee records found." /></section>
    </div>}
  </div>;
}

function ReportBars({ rows, empty }) {
  const maximum = Math.max(...rows.map((row) => row.value), 1);
  return rows.length ? <div className="report-bars">{rows.map((row) => <div className="report-bar-row" key={row.label}><div><span>{row.label}</span><strong>{row.value}</strong></div><div className="report-track"><i style={{ width: `${Math.max(3, row.value / maximum * 100)}%` }} /></div></div>)}</div> : <div className="phase-empty">{empty}</div>;
}
