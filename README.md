# School Operations Platform: Backend (V1)

A role-based REST API for Nigerian secondary schools. It connects students, staff,
attendance, fees and payments, results and report cards, so the principal can see
what is done, what is pending and what needs attention.

Built with Django 5.2 (LTS) and Django REST Framework. SQLite by default and PostgreSQL in production.

> **Working title.** The product name is not decided yet. Everything here says "School Operations Platform".

---

## What V1 does

| Area | What's included |
|---|---|
| **Roles and access** | Four roles: principal, admin, bursar and teacher. Every endpoint checks the role on the server, and teachers only ever see their own classes. |
| **Accounts** | Email + password login (JWT), refresh, logout, profile, change password, password reset by email. Admins manage staff accounts. |
| **School setup** | School profile and settings, academic sessions and terms, classes (e.g. JSS 2A), subjects, grading scale, teacher-to-class assignments. |
| **Students** | Students and guardians (siblings can share a guardian), search and filters, CSV export, **Excel/CSV import with preview**. |
| **Attendance** | Daily class register: everyone defaults to present, so teachers tick only the absent and late. Daily summary per class. |
| **Fees** | Fee structures per class level and term, one-click invoice generation, discounts and scholarships, cancellation. |
| **Payments** | **Paystack online payments** (webhook + verify, idempotent), manual cash / transfer / POS / cheque, reversals, receipt PDFs, parent pay links. |
| **Results** | Score sheets per subject (CA1, CA2, exam), automatic totals and grades, class positions with ties, approval workflow, comments. |
| **Report cards** | PDF per student or whole class, draft watermark before publishing, expiring parent links, optional hold for unpaid fees. |
| **Dashboards** | One per role, including the principal's **"needs attention"** list. |
| **Audit log** | Append-only record of who did what, when and from where. |

The full feature plan, with V2, is in the product plan PDF the team shared. This repo implements V1.

---

## Quick start

Requirements: Python 3.11+.

```bash
git clone https://github.com/Anifowoseolamide/school-ops-backend-.git school-ops-backend
cd school-ops-backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo          # demo school with 300 students, fees, results...
python manage.py runserver
```

Then open:

| URL | What |
|---|---|
| http://localhost:8000/api/docs/ | **Swagger UI**: try every endpoint in the browser |
| http://localhost:8000/api/redoc/ | ReDoc reference |
| http://localhost:8000/api/schema/ | OpenAPI 3 schema (use it to generate a typed frontend client) |
| http://localhost:8000/admin/ | Django admin (create a superuser with `python manage.py createsuperuser`) |

**Postman:** import `postman/School-Ops-API.postman_collection.json` and `postman/School-Ops-Local.postman_environment.json`,
run the *00 Auth* folder, and every endpoint is ready to try. See [postman/README.md](postman/README.md).

### Demo accounts (after `seed_demo`)

All demo accounts use the password **`DemoPass123!`**.

| Role | Email | Notes |
|---|---|---|
| Principal | `principal@sample-school.test` | Sees everything; approves and publishes results |
| Admin | `admin@sample-school.test` | Students, staff, classes, imports, results review |
| Bursar | `bursar@sample-school.test` | Fees, payments, receipts |
| Teacher | `teacher@sample-school.test` | Form teacher of JSS 2A; teaches Mathematics in JSS 1-2 |
| Other teachers | `teacher2@...` to `teacher20@sample-school.test` | |

The seed creates a believable mid-term snapshot: some classes published, some awaiting
approval, missing scores, unmarked registers and a returned sheet. See
[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for a five-minute walkthrough.

To start again: `python manage.py seed_demo --reset` (only works with `DJANGO_DEBUG=true`; it wipes the database).

### Run the tests

```bash
python manage.py test
```

98 tests cover the role matrix, school isolation, imports, payments (including Paystack
webhooks), the results workflow, report cards and dashboards.

---

## How the API works (short version)

```
POST /api/v1/auth/login/          {email, password}  ->  {access, refresh, user{role, capabilities...}}
GET  /api/v1/students/            Authorization: Bearer <access>
```

* **Base URL:** `/api/v1/`
* **Auth:** JWT. Access token lasts 30 minutes; refresh with `POST /api/v1/auth/refresh/`.
* **Money:** always **integers in kobo** (`₦1,500.00` = `150000`). Never floats.
* **Lists:** paginated `{count, next, previous, results}`, with `?page=`, `?page_size=` (max 500), `?search=` and `?ordering=`.
* **Errors:** DRF standard. `400` validation (`{"field": ["message"]}`), `401` not logged in,
  `403` role not allowed, `404` not found or not yours, `409` wrong workflow state, such as editing published results.
* **Dates:** ISO 8601. Times are returned in Africa/Lagos time.

Frontend developers should start with **[docs/FRONTEND_INTEGRATION.md](docs/FRONTEND_INTEGRATION.md)**.

---

## Documentation

| Doc | For |
|---|---|
| [docs/FRONTEND_INTEGRATION.md](docs/FRONTEND_INTEGRATION.md) | Frontend dev: login flow, role routing, screens to endpoints, payments, errors |
| [docs/API_REFERENCE.md](docs/API_REFERENCE.md) | Every endpoint, grouped by module, with the roles allowed |
| [docs/ROLES_AND_PERMISSIONS.md](docs/ROLES_AND_PERMISSIONS.md) | The access matrix and how it is enforced |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Project layout, design decisions, request lifecycle |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Entities and relationships (with diagram) |
| [docs/PAYMENTS.md](docs/PAYMENTS.md) | Invoices, Paystack setup, webhooks, reversals, receipts |
| [docs/RESULTS_AND_REPORT_CARDS.md](docs/RESULTS_AND_REPORT_CARDS.md) | Score entry, workflow, grading, positions, report cards |
| [docs/IMPORTING_STUDENTS.md](docs/IMPORTING_STUDENTS.md) | Excel/CSV format, column names, errors |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Production settings, PostgreSQL, security checklist |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Five-minute demo using the seed data |
| [postman/README.md](postman/README.md) | **Postman collection**: every endpoint with role logins, tests and examples |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Conventions for adding features |

---

## Project layout

```
config/              settings, URLs, WSGI/ASGI
apps/
  core/              roles, permission system, base viewsets, money, signed links, PDFs, seed_demo
  accounts/          User model, login/JWT, profile, password reset, staff management
  schools/           School, settings, sessions, terms, classes, subjects, grading, assignments
  students/          Students, guardians, Excel/CSV importer
  attendance/        Daily registers and summaries
  fees/              Fee structures, invoices, payments, receipts, Paystack, public pay links
  results/           Score sheets, workflow, ranking, report cards
  audit/             Append-only audit log
  notifications/     SMS/email sending with a log (console SMS backend by default)
  dashboards/        Principal, admin, bursar and teacher dashboards
docs/                Documentation and a sample import file
```

## Management commands

| Command | What it does |
|---|---|
| `python manage.py seed_demo [--reset]` | Build the demo school |
| `python manage.py create_school --name "..." --principal-email ... --principal-password ...` | Onboard a real school with its principal account |
| `python manage.py createsuperuser` | Platform operator account for Django admin (not tied to a school) |

## Status and next steps

V1 backend is feature-complete for the demo and a first pilot. Known gaps, by design:

* No parent login yet. Parents use signed links for paying, receipts and report cards (V2: parent portal and WhatsApp).
* Bank transfers are recorded by the bursar. Automatic transfer matching is V2.
* PDFs are generated during the request. Fine for a class (about 1 second for 40 students), but a background queue (Celery) is planned for whole-school runs.
* SMS uses a console backend. Plug in a provider (Termii, Africa's Talking...) via `SMS_BACKEND`.
* Get legal advice on NDPA (Nigeria's data protection law) compliance and on payment handling before going live.
