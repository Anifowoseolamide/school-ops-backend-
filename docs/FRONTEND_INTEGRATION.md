# Frontend integration guide

This is for whoever builds the web app. It covers authentication, how to decide what to
show each role, the endpoints behind each screen, payments, file downloads and error handling.

Interactive docs: **`/api/docs/`** (Swagger). The OpenAPI schema at **`/api/schema/`** can
generate a typed client, for example with `openapi-typescript` or `orval`:

```bash
npx openapi-typescript http://localhost:8000/api/schema/ -o src/api/schema.d.ts
```

---

## 1. Environment

| Setting (backend `.env`) | Why the frontend cares |
|---|---|
| `CORS_ALLOWED_ORIGINS` | Must include your dev server origin, e.g. `http://localhost:5173` |
| `FRONTEND_URL` | Pay links and password-reset links point here, so you must build those pages (section 7) |
| `PAYSTACK_CALLBACK_URL` | Paystack sends parents back here after paying (default `FRONTEND_URL/payments/complete`) |
| `PAYSTACK_SIMULATE=true` | Local development without Paystack keys: payments complete instantly |

---

## 2. Authentication

JWT with access and refresh tokens.

```http
POST /api/v1/auth/login/
Content-Type: application/json

{"email": "bursar@sample-school.test", "password": "DemoPass123!"}
```

```json
{
  "access": "eyJhbGciOi...",
  "refresh": "eyJhbGciOi...",
  "user": {
    "id": 3,
    "email": "bursar@sample-school.test",
    "first_name": "Halima",
    "last_name": "Yusuf",
    "full_name": "Halima Yusuf",
    "phone": "08000000003",
    "role": "bursar",
    "role_label": "Bursar",
    "school": {"id": 1, "name": "Sample Secondary School", "slug": "sample-secondary-school", "logo": null},
    "capabilities": ["dashboard.bursar", "classes.view", "students.view_basic", "guardians.view",
                     "fees.manage", "payments.record", "payments.reverse"],
    "must_change_password": false,
    "last_login": "2026-10-01T15:09:50+01:00"
  }
}
```

* Send `Authorization: Bearer <access>` on every request.
* The access token lasts **30 minutes**. On a `401`, call `POST /api/v1/auth/refresh/` with
  `{"refresh": "..."}`. You get a **new access and a new refresh token** (refresh tokens
  rotate, and the old one stops working). If refresh also fails, send the user to login.
* Logout: `POST /api/v1/auth/logout/` with `{"refresh": "..."}`, then drop both tokens.
* Wrong email or password returns `401` with `{"detail": "Incorrect email or password."}`.
* Login is rate-limited (10 per minute per IP). Too many attempts return `429`.

### First login with a temporary password

When an admin creates a staff account without a password, the API generates a temporary
one and `user.must_change_password` is `true`. **Force the change-password screen** before
anything else:

```http
POST /api/v1/auth/change-password/
{"current_password": "temp-from-admin", "new_password": "..."}
```

### Forgot password

1. `POST /api/v1/auth/password-reset/` `{"email": "..."}` always returns 200.
2. The email links to `FRONTEND_URL/reset-password?uid=...&token=...`. **Build this page.**
3. That page calls `POST /api/v1/auth/password-reset/confirm/` `{"uid", "token", "new_password"}`.

Password rules (Django defaults): at least 8 characters, not all numbers, not too common,
and not too similar to the user's name or email. Errors come back on `new_password`.

### Profile

`GET /api/v1/auth/me/` returns the same `user` object as login. `PATCH` accepts `first_name`, `last_name` and `phone`.

---

## 3. Deciding what to show each role

Use `user.role` to pick the home screen and `user.capabilities` to show or hide menu items
and buttons. **The server enforces every rule anyway**, so hiding a button only improves
the experience.

| Role | Home screen | Main menu |
|---|---|---|
| `principal` | `GET /dashboards/principal/` | Dashboard, Students, Staff, Fees (read), Results (approve/publish), Attendance, Audit log, Settings |
| `admin` | `GET /dashboards/admin/` | Dashboard, Students (+ import), Staff, Classes & subjects, Assignments, Results (review), Attendance, Settings |
| `bursar` | `GET /dashboards/bursar/` | Dashboard, Fee structures, Invoices, Payments, Reports, Students (basic) |
| `teacher` | `GET /dashboards/teacher/` | Dashboard, My classes, Attendance, My score sheets, Comments (if form teacher) |

Capabilities list (from `apps/core/roles.py`):

| Capability | Principal | Admin | Bursar | Teacher |
|---|:-:|:-:|:-:|:-:|
| `school.manage` | ✓ | ✓ | | |
| `staff.view` / `staff.manage` | view | manage | | |
| `classes.view` / `classes.manage` / `classes.view_own` | view | manage | view | own |
| `assignments.manage` | | ✓ | | |
| `students.view` / `students.manage` / `students.view_basic` / `students.view_own` | view | manage | basic | own |
| `students.import` | | ✓ | | |
| `guardians.view` / `guardians.manage` / `guardians.view_own` | view | manage | view | own |
| `attendance.view` / `attendance.mark_own` | view | view | | mark own |
| `fees.view` / `fees.manage` | view | | manage | |
| `payments.view` / `payments.record` / `payments.reverse` | view | | record, reverse | |
| `results.view` | ✓ | ✓ | | |
| `results.enter_own` | | | | ✓ |
| `results.review` | | ✓ | | |
| `results.approve` / `results.publish` / `results.unlock` | ✓ | | | |
| `results.comment_principal` / `results.comment_class_teacher` | principal | | | class teacher |
| `report_cards.view` / `report_cards.generate` | view | generate | | |
| `audit.view` | ✓ | | | |

A `403` means the role cannot do this. A `404` on a specific record usually means it
exists but is outside the user's scope (for example another teacher's class). Treat both as "not available".

---

## 4. Conventions

### Money

**All amounts are integers in kobo.** `₦240,000.00` is `24000000`. Fields end in `_kobo`.

```ts
const naira = (kobo: number) =>
  new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN" }).format(kobo / 100);
// When the user types "15,000" -> send Math.round(15000 * 100)
```

### Pagination, search, filters, ordering

```
GET /api/v1/students/?page=2&page_size=50&search=okafor&classroom=3&ordering=last_name
```

```json
{"count": 300, "next": "...?page=3", "previous": "...?page=1", "results": [ ... ]}
```

* `page_size` max is 500.
* `ordering=-field` for descending. Allowed fields are listed per endpoint in Swagger.
* A few endpoints return a plain list or object (dashboards, summaries, reports, grade bands).
  Swagger shows the shape.

### Errors

```json
// 400 validation: field errors (and sometimes "non_field_errors")
{"admission_number": ["Another student already has this admission number."]}

// 400/401/403/404/409/429/502/503: a single message
{"detail": "This sheet has been submitted. Ask the admin to return it if you need to make changes.",
 "code": "workflow_error"}
```

| Status | Meaning | What to do |
|---|---|---|
| 400 | Invalid input | Show field errors next to inputs; show `detail`/`non_field_errors` as a banner |
| 401 | Not logged in / token expired | Refresh token, retry once, else go to login |
| 403 | Role not allowed | Hide the feature; show "You don't have access" |
| 404 | Not found or not in your scope | "Not found" |
| 409 | Valid request but wrong state (`code`: `workflow_error`, `conflict`, `protected`) | Show `detail`. It explains what to do next |
| 429 | Too many requests | Wait and retry |
| 502 / 503 | Payment provider down / not configured | Show `detail` (written for end users) |

### Dates and times

Dates are `YYYY-MM-DD`. Datetimes are ISO 8601 with offset, in Africa/Lagos time.

### File downloads (PDF, CSV)

Endpoints that return files need the auth header, so fetch them as a blob:

```ts
const res = await fetch(`${API}/api/v1/fees/payments/${id}/receipt/`, { headers: { Authorization: `Bearer ${token}` } });
const url = URL.createObjectURL(await res.blob());
window.open(url);            // or create an <a download> link
```

Public links (pay, receipt, report card) need no auth header and can be opened directly.

---

## 5. Screens and the endpoints behind them

All paths below are relative to `/api/v1/`.

### Principal dashboard

`GET dashboards/principal/` returns:

```jsonc
{
  "term": {"id": 1, "name": "First Term 2026/2027", "start_date": "...", "end_date": "..."},
  "counts": {"students": 300, "staff": 23, "staff_by_role": {...}, "classes": 12},
  "fees": {"term": {...}, "totals": {"billed_kobo": 6419000000, "collected_kobo": 4803400000,
           "outstanding_kobo": 1615600000, "collection_rate": 74.8, "paid": 180, "part_paid": 75, "unpaid": 45},
           "classes": [{"classroom": {"id": 1, "name": "JSS 1A"}, "billed_kobo": ..., "collection_rate": 92.1, ...}]},
  "attendance_today": {"students": 300, "marked": 225, "attendance_rate": 94.2, "classes_marked": 9, "classes_total": 12, ...},
  "results": {"sheets_total": 96, "sheets_submitted": 85, "sheets_pending": 11,
              "class_results": {"open": 7, "in_review": 2, "approved": 1, "published": 1}},
  "needs_attention": [
    {"severity": "high", "type": "scores_missing", "message": "10 teacher(s) have 11 score sheet(s) not submitted",
     "count": 11, "link": {"endpoint": "/api/v1/results/missing/", "params": {"term": 1}}},
    {"severity": "medium", "type": "attendance_not_marked", "message": "3 class(es) have not marked attendance today",
     "classes": ["JSS 2A", "SS 1B", "SS 3A"], ...}
  ],
  "recent_payments": [...],
  "staff_activity": [{"id": 5, "name": "...", "role": "teacher", "last_login": "...", "last_activity": "..."}]
}
```

`needs_attention[].link` tells you which list to open when the item is clicked. `type` is
one of `scores_missing`, `results_awaiting_approval`, `results_ready_to_publish`,
`students_owing`, `attendance_not_marked` or `no_current_term`.

### Students

| Screen | Calls |
|---|---|
| List with filters | `GET students/?classroom=&status=&gender=&search=` |
| Details | `GET students/{id}/` |
| Create / edit (admin) | `POST students/`, `PATCH students/{id}/` with `guardian_ids: [..]` |
| Guardians | `GET/POST guardians/`. Create the guardian first, then link it with `guardian_ids` |
| Export CSV | `GET students/export/` (same filters as the list) |
| Class list | `GET classes/{id}/students/` |
| Import (admin) | See [IMPORTING_STUDENTS.md](IMPORTING_STUDENTS.md) |

The bursar receives a smaller student object (`id, admission_number, full_name, classroom, status, guardians`).

### Staff (admin manages, principal views)

`GET staff/?role=teacher&is_active=true`, `POST staff/`, `PATCH staff/{id}/`,
`POST staff/{id}/deactivate/`, `POST staff/{id}/activate/`, `POST staff/{id}/reset-password/`.
`POST staff/` returns `temporary_password` **once**. Show it to the admin to pass on.

### School setup (admin; principal can edit settings)

`school/`, `school/settings/`, `sessions/`, `terms/` (`GET terms/current/`,
`POST terms/{id}/set-current/`), `classes/`, `subjects/`, `grade-bands/`, `assignments/`.

### Attendance (teacher)

```http
GET  attendance/register/?classroom=3&date=2026-10-01
POST attendance/register/
{"classroom": 3, "date": "2026-10-01",
 "records": [{"student": 41, "status": "absent", "note": "Sick"}, {"student": 47, "status": "late"}]}
```

Send only the exceptions. Everyone else is saved as present. `status` is one of
`present | absent | late | excused`. Saving again overwrites the day. Admin and principal
use `GET attendance/summary/?date=` and `GET attendance/records/?classroom=&date_from=&date_to=`.

### Fees (bursar)

| Screen | Calls |
|---|---|
| Fee structures | `GET/POST fees/structures/` with `items: [{name, amount_kobo}]` |
| Generate invoices | `POST fees/structures/{id}/generate-invoices/` (safe to repeat) |
| Invoice list | `GET fees/invoices/?term=&classroom=&status=unpaid\|part_paid\|paid&has_balance=true&search=&ordering=-balance_kobo` |
| Invoice details | `GET fees/invoices/{id}/` (lines, adjustments, payments) |
| Discount / scholarship | `POST fees/invoices/{id}/adjustments/` `{kind, amount_kobo, reason}` |
| Record a payment | `POST fees/payments/` `{invoice, amount_kobo, method: cash\|bank_transfer\|pos\|cheque, external_reference?, paid_at?, payer_name?, note?}` |
| Receipt | `GET fees/payments/{id}/receipt/` (PDF), `GET .../receipt-link/`, `POST .../send-receipt/` |
| Reverse | `POST fees/payments/{id}/reverse/` `{reason}` |
| Pay link | `GET fees/invoices/{id}/pay-link/`, `POST fees/invoices/{id}/send-pay-link/` |
| Reports | `GET fees/reports/outstanding/?term=`, `GET fees/reports/collections/?date_from=&date_to=` |

### Results

**Teacher, score entry:**

```http
GET results/sheets/                       # my sheets with progress
GET results/sheets/{id}/                  # rows: one per student, plus maxima and can_edit
PUT results/sheets/{id}/scores/
{"scores": [{"student": 41, "ca1": 15, "ca2": 14, "exam": 48}, {"student": 42, "exam": null}]}
POST results/sheets/{id}/submit/
```

* Send only changed fields. `null` clears a score. Decimals like `12.5` are allowed.
* `total`, `grade` and `remark` are calculated by the server once all three scores are present.
* Use `can_edit` from the sheet detail to enable or disable inputs.
* After submit, edits return `409` until an admin returns the sheet.

**Admin:** `POST results/setup/` (once per term, and again after changing assignments),
`POST results/sheets/{id}/return/` `{note}`, `POST results/class-results/{id}/begin-review/`,
`GET results/missing/`, `GET results/class-results/{id}/broadsheet/`,
`GET results/class-results/{id}/report-cards/` (PDF).

**Principal:** `POST results/class-results/{id}/approve/`, `.../send-back/`, `.../publish/`,
`.../unlock/` `{reason}`, `POST .../send-report-cards/`.

**Comments:** `GET results/class-results/{id}/summaries/`, then
`PATCH results/summaries/{id}/` with `class_teacher_comment` (form teacher) or `principal_comment` (principal).

Show the workflow status from `class_result.status`: `open → in_review → approved → published`.
See [RESULTS_AND_REPORT_CARDS.md](RESULTS_AND_REPORT_CARDS.md).

---

## 6. Online payments (parent flow)

Parents do not log in. The bursar sends a **pay link**: `FRONTEND_URL/pay/<token>`.

**Build a public page at `/pay/:token`:**

```ts
// 1. Show the invoice
GET /api/v1/public/pay/{token}/
// -> {number, school, student, term, lines, total_kobo, amount_paid_kobo, balance_kobo,
//     allow_part_payment, minimum_part_payment_kobo, online_payments_available}

// 2. Parent enters email (and an amount if part payment is allowed) -> start payment
POST /api/v1/public/pay/{token}/initialize/   {"email": "...", "amount_kobo": 5000000}
// -> {"reference": "PSK-...", "authorization_url": "https://checkout.paystack.com/...",
//     "access_code": "...", "public_key": "pk_test_...", "simulated": false}

// 3. Redirect: window.location.href = authorization_url
//    (or use Paystack Popup / InlineJS with access_code + public_key)
```

**Build the callback page at `/payments/complete`.** Paystack redirects there with `?reference=...`:

```ts
GET /api/v1/public/payments/verify/?reference=PSK-...
// -> {"status": "successful" | "pending" | "failed", "amount_kobo", "paid_at",
//     "receipt_number", "receipt_url", "invoice_balance_kobo"}
```

Show success with a **Download receipt** button (`receipt_url` is a public PDF link). If
`pending`, poll every few seconds for up to a minute. The webhook may arrive slightly later.

In local development with `PAYSTACK_SIMULATE=true` and no keys, `authorization_url` points
straight back to your callback page with `simulated=true`, and `verify` marks the payment successful.

Errors here: `400` for amount rules (`detail` on `amount_kobo`), `404` for an invalid or
expired link, `409` if already paid, `503` if online payments aren't set up, and `502` if Paystack is down.

---

## 7. Public pages you need to build

| Route (frontend) | Purpose | API |
|---|---|---|
| `/reset-password?uid&token` | Set a new password | `POST auth/password-reset/confirm/` |
| `/pay/:token` | Parent pays fees | `GET public/pay/{token}/`, `POST .../initialize/` |
| `/payments/complete?reference` | After Paystack checkout | `GET public/payments/verify/` |

Receipt and report-card links point **directly at the API** (`BACKEND_URL/api/v1/public/...`)
and return PDFs, so no frontend page is needed for them.

---

## 8. Things that are easy to get wrong

* Don't format or calculate money with floats. Divide by 100 only for display.
* Don't calculate totals, grades, balances or positions in the frontend. Show what the API returns.
* Always re-read the object after an action (`approve`, `submit`, `reverse`...). Actions return the updated object.
* Teachers see a filtered world, so expect counts to differ by role.
* `must_change_password` must block the app until the password is changed.
