# API reference

Base URL: `/api/v1/`. Auth: `Authorization: Bearer <access token>` unless marked **public**.
Live, always-current docs with request and response schemas: **`/api/docs/`** (Swagger) or `/api/redoc/`.

Role key: **P** principal, **A** admin, **B** bursar, **T** teacher (own classes/subjects only).
Money fields are integers in **kobo**.

---

## Auth

| Method | Path | Roles | Description |
|---|---|---|---|
| POST | `auth/login/` | public | `{email, password}` returns `{access, refresh, user}` |
| POST | `auth/refresh/` | public | `{refresh}` returns `{access, refresh}` (rotates) |
| POST | `auth/logout/` | any | `{refresh}` blacklists it. Returns 205 |
| GET, PATCH | `auth/me/` | P A B T | Own profile, role and capabilities. PATCH: `first_name`, `last_name`, `phone` |
| POST | `auth/change-password/` | any | `{current_password, new_password}` |
| POST | `auth/password-reset/` | public | `{email}`. Always 200; emails a link if the account exists |
| POST | `auth/password-reset/confirm/` | public | `{uid, token, new_password}` |

## Staff

| Method | Path | Roles | Description |
|---|---|---|---|
| GET | `staff/` | P A | Filters: `role`, `is_active`; `search` name/email/phone |
| POST | `staff/` | A | Create. Omit `password` to get a one-time `temporary_password`. Role cannot be `principal` |
| GET | `staff/{id}/` | P A | Includes `form_classes` and current `teaching` assignments for teachers |
| PUT, PATCH | `staff/{id}/` | A | Edit (not the principal; not your own role) |
| POST | `staff/{id}/deactivate/` | A | Blocks login. Staff are never deleted |
| POST | `staff/{id}/activate/` | A | |
| POST | `staff/{id}/reset-password/` | A | Returns a new `temporary_password` |

## School setup

| Method | Path | Roles | Description |
|---|---|---|---|
| GET / PATCH | `school/` | all / P A | Name, address, phone, email, motto, logo |
| GET / PATCH | `school/settings/` | all / P A | `ca1_max`, `ca2_max`, `exam_max` (must total 100), `allow_part_payment`, `minimum_part_payment_kobo`, `invoice_prefix`, `receipt_prefix`, `hold_report_cards_for_debtors`, `report_card_footer` |
| CRUD | `sessions/` | read all / write P A | Academic sessions, e.g. `2026/2027` |
| POST | `sessions/{id}/set-current/` | P A | |
| CRUD | `terms/` | read all / write P A | `name`: `first`, `second`, `third`. Filter `session`, `is_current` |
| GET | `terms/current/` | all | 404 with `code: no_current_term` if none |
| POST | `terms/{id}/set-current/` | P A | Also makes its session current |
| CRUD | `classes/` | read P A B T(own) / write A | `level` (`JSS1`…`SS3`), `arm`, `class_teacher`, `capacity`; `student_count` included |
| GET | `classes/{id}/students/` | P A T(own) | Active students in the class |
| CRUD | `subjects/` | read all / write A | |
| CRUD | `assignments/` | read P A T(own) / write A | `{session, classroom, subject, teacher}`. One teacher per subject per class per session |
| CRUD | `grade-bands/` | read all / write P A | Grading scale (default WAEC A1–F9). Not paginated |

## Students

| Method | Path | Roles | Description |
|---|---|---|---|
| GET | `students/` | P A B(basic) T(own) | Filters: `classroom`, `status`, `gender`, `classroom__level`; `search` name/admission no; `ordering` |
| POST | `students/` | A | `{admission_number, first_name, middle_name?, last_name, gender?, date_of_birth?, classroom?, status?, admission_date?, address?, guardian_ids?: []}` |
| GET | `students/{id}/` | P A B(basic) T(own) | |
| PUT, PATCH | `students/{id}/` | A | |
| DELETE | `students/{id}/` | A | 409 `protected` if the student has invoices, scores or attendance. Set `status: withdrawn` instead |
| GET | `students/export/` | P A | CSV; accepts the list filters |
| CRUD | `guardians/` | read P A B T(own) / write A | `{first_name, last_name, relationship, phone, alt_phone, email, address, occupation}` |
| POST | `students/imports/preview/` | A | multipart: `file` (.csv/.xlsx), optional `column_mapping` JSON. Returns a report; nothing is created |
| POST | `students/imports/{id}/commit/` | A | Creates the valid rows |
| GET | `students/imports/`, `students/imports/{id}/` | A | Import history with row errors |

## Attendance

| Method | Path | Roles | Description |
|---|---|---|---|
| GET | `attendance/register/?classroom=&date=` | P A T(own) | Register for a day; unmarked students show as present with `is_marked: false` |
| POST | `attendance/register/` | T(own) | `{classroom, date?, records: [{student, status, note?}]}`. Omitted students are saved as present. Status: `present`, `absent`, `late`, `excused` |
| GET | `attendance/summary/?date=` | P A T(own) | Per class: marked or not, present, absent, late, rate |
| GET | `attendance/records/` | P A T(own) | Filters: `student`, `classroom`, `term`, `date`, `date_from`, `date_to`, `status` |
| GET | `attendance/students/{id}/summary/?term=` | P A T(own) | Term totals for one student |

## Fees and payments

| Method | Path | Roles | Description |
|---|---|---|---|
| CRUD | `fees/structures/` | read P B / write B | `{term, level, name?, due_date?, notes?, items: [{name, amount_kobo, position?}]}`. Items are replaced on update. Delete fails (409) once invoices exist |
| POST | `fees/structures/{id}/generate-invoices/` | B | One invoice per active student at that level; skips students who already have one |
| GET | `fees/invoices/` | P B | Filters: `term`, `classroom`, `student`, `status` (`unpaid`, `part_paid`, `paid`, `cancelled`), `level`, `has_balance`; `search`; `ordering` (`-balance_kobo` …) |
| POST | `fees/invoices/` | B | One-off invoice `{student, term, lines: [{description, amount_kobo}], due_date?, notes?}`. 409 if the student already has one for the term |
| GET | `fees/invoices/{id}/` | P B | With `lines`, `adjustments`, `payments` |
| POST | `fees/invoices/{id}/adjustments/` | B | `{kind: discount\|scholarship\|waiver\|surcharge, amount_kobo, reason}` |
| POST | `fees/invoices/{id}/cancel/` | B | `{reason}`. 409 if it has payments |
| GET | `fees/invoices/{id}/pay-link/` | P B | `{url, expires_in_days}`; parent pay page link |
| POST | `fees/invoices/{id}/send-pay-link/` | B | SMS + email to the student's guardians |
| GET | `fees/payments/` | P B | Filters: `invoice`, `student`, `method`, `status`, `term`, `classroom`, `date_from`, `date_to`; `search` |
| POST | `fees/payments/` | B | Record money received: `{invoice, amount_kobo, method: cash\|bank_transfer\|pos\|cheque, paid_at?, external_reference?, payer_name?, note?}`. Issues a receipt |
| GET | `fees/payments/{id}/` | P B | |
| POST | `fees/payments/{id}/reverse/` | B | `{reason}`. Creates a negative payment; the original is kept |
| GET | `fees/payments/{id}/receipt/` | P B | Receipt PDF |
| GET | `fees/payments/{id}/receipt-link/` | P B | Public receipt link for parents |
| POST | `fees/payments/{id}/send-receipt/` | B | Re-send receipt link to guardians |
| GET | `fees/reports/outstanding/?term=` | P B | Billed, collected and outstanding per class, plus totals |
| GET | `fees/reports/collections/?date_from=&date_to=` | P B | Money received by method and by day |

## Results

| Method | Path | Roles | Description |
|---|---|---|---|
| POST | `results/setup/` | A | `{term?}`. Creates class results and score sheets from assignments. Idempotent |
| GET | `results/sheets/` | P A T(own) | Filters: `term`, `classroom`, `subject`, `teacher`, `status`, `class_result`. Includes `progress` |
| GET | `results/sheets/{id}/` | P A T(own) | One `row` per student, plus `maxima` and `can_edit` |
| PUT, PATCH | `results/sheets/{id}/scores/` | T (sheet owner) | `{scores: [{student, ca1?, ca2?, exam?}]}` |
| POST | `results/sheets/{id}/submit/` | T (sheet owner) | Every student must have all three scores |
| POST | `results/sheets/{id}/return/` | A | `{note}`. Sends back to the teacher; reopens class review |
| GET | `results/missing/?term=` | P A | Unsubmitted sheets with missing counts, grouped by teacher |
| GET | `results/class-results/` | P A T(form class) | Filters: `term`, `classroom`, `status` (`open`, `in_review`, `approved`, `published`) |
| GET, PATCH | `results/class-results/{id}/` | read P A T / write P A | PATCH: `next_term_begins` |
| POST | `results/class-results/{id}/begin-review/` | A | open to in_review (all sheets submitted) |
| POST | `results/class-results/{id}/approve/` | P | in_review to approved |
| POST | `results/class-results/{id}/send-back/` | P | approved to in_review |
| POST | `results/class-results/{id}/publish/` | P | approved to published |
| POST | `results/class-results/{id}/unlock/` | P | `{reason}`; published to in_review (audited) |
| GET | `results/class-results/{id}/summaries/` | P A T(form class) | Totals, averages, positions, comments |
| GET | `results/class-results/{id}/broadsheet/` | P A | Every student × subject total |
| GET | `results/class-results/{id}/report-cards/` | P A | One PDF for the whole class (watermarked until published) |
| POST | `results/class-results/{id}/send-report-cards/` | P A | Send report-card links to guardians (published only) |
| GET, PATCH | `results/summaries/{id}/` | read P A T(form class) / write P T | PATCH `class_teacher_comment` (form teacher) or `principal_comment` (principal) |
| GET | `results/summaries/{id}/report-card/` | P A T(form class) | One student's PDF |
| GET | `results/summaries/{id}/share-link/` | P A | Expiring public link (published only) |

## Dashboards

| Method | Path | Roles |
|---|---|---|
| GET | `dashboards/principal/` | P |
| GET | `dashboards/admin/` | A P |
| GET | `dashboards/bursar/` | B P |
| GET | `dashboards/teacher/` | T |

## Audit

| Method | Path | Roles | Description |
|---|---|---|---|
| GET | `audit/logs/` | P | Filters: `actor`, `actor_role`, `action` (prefix, e.g. `payment`), `object_type`, `object_id`, `date_from`, `date_to`; `search` |
| GET | `audit/logs/{id}/` | P | |

## Public (signed links, no login)

| Method | Path | Description |
|---|---|---|
| GET | `public/pay/{token}/` | Invoice summary for the parent pay page |
| POST | `public/pay/{token}/initialize/` | `{email, amount_kobo?, payer_name?}` returns a Paystack `authorization_url` |
| GET | `public/payments/verify/?reference=` | Check payment status after checkout |
| GET | `public/receipts/{token}/` | Receipt PDF |
| GET | `public/report-cards/{token}/` | Report card PDF (published only; 403 if held for unpaid fees) |
| POST | `payments/paystack/webhook/` | Called by Paystack only (signature checked) |

## Other

| Path | Description |
|---|---|
| `/health/` | `{"status": "ok"}` for uptime checks |
| `/api/schema/` | OpenAPI 3 schema |
| `/api/docs/`, `/api/redoc/` | Interactive docs |
| `/admin/` | Django admin (platform operators) |
