# Architecture

## Overview

```
                Frontend (React or any SPA)                    Parents (no login)
                         │  JWT                                      │ signed links
                         ▼                                           ▼
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │  Django + Django REST Framework  (/api/v1/)                                   │
 │                                                                              │
 │  Request ─► JWT auth ─► RolePermission ─► View (school-scoped queryset)      │
 │                                             │                                │
 │                                             ▼                                │
 │                                   Service functions (business rules)         │
 │                                             │                                │
 │                       ┌─────────────────────┼─────────────────────┐          │
 │                       ▼                     ▼                     ▼          │
 │                 Models / DB          Audit log (append-only)  Notifications   │
 └───────────────────────┬──────────────────────────────────────────┬───────────┘
                         ▼                                          ▼
                SQLite (dev) / PostgreSQL               Email (SMTP) · SMS (pluggable)
                                         ▲
                     Paystack ──webhook──┘  (and API calls to initialize/verify)
```

## Principles

1. **Roles are enforced on the server, always.** The frontend's `capabilities` list only improves the experience. See [ROLES_AND_PERMISSIONS.md](ROLES_AND_PERMISSIONS.md).
2. **Multi-school from day one.** Every school-owned table has a `school` foreign key, and every query is filtered by the user's school. A second school is just more rows.
3. **Business rules live in `services.py`**, not in views or serializers. Views parse input, check access, call a service and return the result. Services are easy to test and to reuse from management commands, webhooks or future background jobs.
4. **Derived values are computed, never typed in.** Invoice balance and status come from lines, adjustments and payments (`Invoice.recalculate()`). Score totals, grades, averages and positions come from scores (`results.services`).
5. **History is never destroyed.** Payments cannot be edited or deleted; corrections are reversals. Staff are deactivated, not deleted. Students with records cannot be deleted (409). The audit log is append-only.
6. **Boring, standard tools.** Django 5.2 LTS, DRF viewsets and routers, SimpleJWT, django-filter, drf-spectacular. A new developer who knows DRF can be productive in an hour.

## Apps

| App | Owns | Key files |
|---|---|---|
| `core` | Roles, permission system, base viewsets, school scoping, money helpers, signed links, PDF styles, sequences, `seed_demo` | `permissions.py`, `viewsets.py`, `roles.py`, `links.py` |
| `accounts` | Custom `User` (email login, `school`, `role`), JWT views, staff management | `models.py`, `serializers.py`, `views.py` |
| `schools` | School, settings, sessions, terms, classes, subjects, assignments, grade bands | `services.py` (current term, teacher scope, grading) |
| `students` | Students, guardians, import jobs | `importer.py` |
| `attendance` | Attendance records, registers, summaries | `services.py` |
| `fees` | Fee structures, invoices, adjustments, payments, receipts, Paystack | `services.py`, `paystack.py`, `views_public.py`, `pdf.py` |
| `results` | Class results, score sheets, scores, summaries, report cards | `services.py`, `report_cards.py` |
| `audit` | `AuditLog` and `record_audit()` | `services.py` |
| `notifications` | `NotificationLog`, SMS backends, email | `services.py`, `backends.py` |
| `dashboards` | Read-only aggregations per role | `services.py` |

## Request lifecycle (example: bursar records a cash payment)

1. `POST /api/v1/fees/payments/` with a JWT.
2. `JWTAuthentication` loads the user. `RolePermission` checks `bursar ∈ write_roles`.
3. `PaymentViewSet.create` validates input with `ManualPaymentSerializer`. `invoice` is a `SchoolPK`, so an invoice from another school fails validation.
4. `services.record_manual_payment()` locks the invoice row, validates the amount against the balance, rejects duplicate bank references, creates the `Payment`, recalculates the invoice and issues a `Receipt` with the next receipt number, all in one transaction.
5. The view writes an `AuditLog` entry and returns the payment with its receipt number.

## Key decisions

| Decision | Why |
|---|---|
| JWT (access 30 min, rotating refresh 7 days, blacklist on logout) | Standard for SPAs and mobile; no CSRF handling on the frontend |
| Integers in kobo for money | No float rounding errors; matches Paystack's API |
| Paystack confirmation via webhook **and** verify endpoint, both idempotent | The redirect can fail and webhooks can be delayed or repeated; either path settles the payment exactly once |
| Signed, expiring tokens (Django `signing`) for parent links | No parent accounts in V1, but links cannot be guessed or reused forever |
| Per-school sequences for invoice and receipt numbers | Human-readable numbers (`RCT-000123`) that never collide |
| Synchronous PDF generation | About a second for a class; avoids running Redis/Celery for the pilot. Move to a task queue when whole-school runs are needed |
| Pluggable SMS backend, console by default | Pick a provider later without code changes elsewhere |
| SQLite by default, PostgreSQL by env var | Zero setup for development and demos; same code in production |
| Teacher assignments are per **session**; score sheets are per **term** | Teachers usually keep their classes all year; results are termly |

## Where to add V2 features

| V2 feature | Where it plugs in |
|---|---|
| Parent portal / WhatsApp | New `parents` app with a `ParentUser` linked to `Guardian`; reuse `fees.services` and `results.report_cards` |
| Automatic transfer matching | New service in `fees` that calls `confirm_online_payment`-style logic for bank webhooks |
| Absence alerts, fee reminders | `notifications.services.notify_guardians` + a scheduler (Celery beat or cron + management command) |
| School Pulse daily summary | Reuse `dashboards.services.principal_dashboard` and send via notifications |
| Background jobs | Add Celery; move `render_report_cards` and imports into tasks |
