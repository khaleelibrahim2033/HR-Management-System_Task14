# WorkSphere HRMS

WorkSphere is a full-stack HR management system built with FastAPI, SQLAlchemy, SQLite, and React. It includes role-based authorization, employee self-service, leave policies and balances, payroll, shift and attendance automation, a team leave calendar, protected employee documents, performance reviews, analytics, and employee search filters.

## Requirements

- Python 3.11+
- Node.js 20+

## Start the API

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a unique `JWT_SECRET_KEY` of at least 32 characters in `backend/.env` (for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`). To enable HR administration, also set all three `BOOTSTRAP_ADMIN_*` values to your chosen administrator credentials. Then run:

```powershell
uvicorn app.main:app --reload
```

The API and interactive docs are available at `http://localhost:8000` and `http://localhost:8000/docs`.

The optional `BOOTSTRAP_ADMIN_*` settings create one administrator if no admin account exists. After login, an administrator can create accounts, change roles, and deactivate users from User management or the `/auth/users` API. Public registration always creates an employee and cannot select a privileged role. HR/Admin accounts can onboard employee accounts from the Employees screen.

JWT role claims are checked against the current active database account on each authenticated request; role changes and deactivation invalidate previously issued tokens. HR/Admin can manage employee records, review leave, view attendance, and generate payroll. Employees only receive their own profile, attendance, leave, and payroll data. Administrator analytics and user-role management are admin-only.

Leave policies are initialized with 10 sick, 10 casual, and 15 paid days for a new database. Approved requests deduct calendar days from the employee balance; pending requests reserve available capacity. Attendance check-ins after `ATTENDANCE_LATE_AFTER` (09:00 by default) in server-local time are marked late. Missing attendance is automatically recorded for the previous working day when attendance history is requested, except when an approved leave covers that date. Existing databases are upgraded in place for the added user, attendance, and payroll fields.

## Phase 3 features

- Morning, Evening, and Night shifts are created by default. HR/Admin can define additional shifts and assign one current shift per employee. Early/late check-ins and early check-outs are flagged against shift hours; late arrivals notify the employee and HR/Admin. Missing records for the previous working day are marked absent after the assigned shift ends when attendance history is requested.
- The leave calendar displays pending and approved team leave for a selected date range and department. Employee leave requests cannot overlap another active request for the same employee.
- Documents accept PDF, DOC/DOCX, PNG, and JPG/JPEG files up to `DOCUMENT_MAX_SIZE_BYTES` (10 MiB by default). Files are stored outside the public web root in `DOCUMENT_STORAGE_DIR` (defaults to `backend/uploads`) and are only served through authenticated, ownership-checked download routes. HR/Admin can manage documents across employees; employees can access only their own.
- HR/Admin can add 1–5 performance reviews; employees can view their own review history.
- `/reports/analytics` provides attendance, leave, department headcount, and performance summaries with date and department filters. Employee directory filters include name/email/title/department search, role, status, today's attendance, and minimum performance rating.
- Notifications are refreshed by the web app every 30 seconds while signed in. Late check-ins, leave decisions, and payroll generation create notifications.

Set `DOCUMENT_STORAGE_DIR` to a private persistent directory and tune `DOCUMENT_MAX_SIZE_BYTES` for deployment. Keep that storage outside any static-file server and back it up using the same controls as other HR records.


## Phase 4 features

- **Employee onboarding**: HR/Admin can assign onboarding checklist items; employees can view and complete their own items; progress is tracked per employee.
- **Resignation and exit management**: employees submit resignations and track status; HR/Admin approve or reject pending requests.
- **Internal announcements**: HR/Admin publish announcements and authenticated employees can view details.
- **Internal tasks**: HR/Admin assign tasks and due dates; employees update their assigned task status.
- **Integrations and exports**: CSV/PDF report export endpoints and downloadable iCalendar (`.ics`) events; email notifications can be configured with SMTP environment settings. Google Calendar OAuth is optional and is not enabled until credentials are configured.
- **Employee feedback**: employees submit a message and 1–5 rating; HR/Admin can review submitted feedback.
- **Profile and settings**: users update permitted profile fields, change their password, and manage notification preferences.

Phase 4 API routes are documented automatically in Swagger at `/docs`. New tables are created by the application's SQLAlchemy metadata initialization when the backend starts. Back up your database before running the updated version.

## Start the web app

In a second PowerShell window:

```powershell
cd frontend
npm install
npm run dev
```

The frontend defaults to `http://localhost:8000` for the API. Set `VITE_API_URL` in `frontend/.env` to override it.

## Tests and build

```powershell
cd backend
python -m pip install pytest httpx
python -m pytest
```

```powershell
cd frontend
npm run build
```

The API uses SQLite by default. Set `DATABASE_URL` to a supported SQLAlchemy URL to use another database. `FRONTEND_ORIGINS` accepts a comma-separated list of allowed browser origins.

## Use MySQL with MySQL Workbench

1. Install and start MySQL Server, then open MySQL Workbench and connect to your local server (typically host `127.0.0.1`, port `3306`).
2. In Workbench, open a SQL tab and create a database:

   ```sql
   CREATE DATABASE worksphere CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

3. In `backend/.env`, change `DATABASE_URL` to your MySQL server credentials:

   ```dotenv
   DATABASE_URL=mysql+pymysql://root:YOUR_PASSWORD@127.0.0.1:3306/worksphere?charset=utf8mb4
   ```

   Replace `root` and `YOUR_PASSWORD` with your MySQL username and password. If the password contains reserved URL characters (such as `@`, `/`, or `:`), URL-encode it.
4. From the `backend` directory, install requirements if you have not already and start the API with `uvicorn app.main:app --reload`. On startup, the app creates its tables in the selected database.
5. In Workbench, refresh the Schemas panel and expand `worksphere` to see the tables.

Use the same host, port, username, and password in Workbench that you used in `DATABASE_URL`. The database must already exist before starting the API. Keep using the SQLite URL to run the app with its local SQLite database instead.

## Phase 1 notes

- Payroll values use the currency configured in the interface (USD in this starter); payslips show basic salary, allowances, bonus, deductions, and net salary.
- Payslips download as a simple text file.
- SQLite tables are created automatically for local development; production deployments should use managed secrets, HTTPS, a production database, and versioned schema migrations.
