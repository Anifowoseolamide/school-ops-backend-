# Postman collection

| File | What |
|---|---|
| `School-Ops-API.postman_collection.json` | All V1 endpoints (156 requests in 15 folders) with descriptions, role-based logins, chained variables, test scripts and real example responses |
| `School-Ops-Local.postman_environment.json` | `base_url=http://localhost:8000` and the demo logins |
| `School-Ops-Staging.postman_environment.json` | Template for a deployed server: fill in `base_url` and real credentials |
| `tools/build_collection.py` | Generates the collection (edit this, not the JSON) |
| `tools/run_collection.mjs` | Dependency-free runner (Node 18+) used to test the collection end to end |

## Use it in Postman

1. Start the backend with demo data:
   ```bash
   python manage.py migrate
   python manage.py seed_demo          # or: seed_demo --reset to start fresh
   python manage.py runserver
   ```
   For the online-payment folder without Paystack keys, put `PAYSTACK_SIMULATE=true` in `.env` (with `DJANGO_DEBUG=true`).
2. In Postman: **Import** both the collection and `School-Ops-Local` environment, then select the environment (top right).
3. Open **00 Auth** and click **Run** (or send the four *Login as …* requests). Tokens are saved automatically.
4. Use any request. Each one already uses the right role's token; its description says which role and what the request does.

Access tokens last 30 minutes: if you start getting `401`, run **00 Auth** again.

## Run everything

The collection is designed to run top to bottom on the seed data, and to be run again:
test records it creates are deleted, payments it makes are reversed and the results workflow it
walks through (approve, publish, unlock) ends where it started.

* **Postman:** right-click the collection, choose **Run collection**, then **Run**.
  *04 Student import*: Postman needs you to pick the upload file once (`docs/samples/students_sample.csv`).
* **Command line (no installs):**
  ```bash
  node postman/tools/run_collection.mjs \
    --collection postman/School-Ops-API.postman_collection.json \
    --environment postman/School-Ops-Local.postman_environment.json
  ```
  Add `--folder "06 Fees & invoices"` to run one folder, or `--report run.json` to save every response.
* **Newman** (Postman's CLI) also works:
  `npx newman run postman/School-Ops-API.postman_collection.json -e postman/School-Ops-Local.postman_environment.json`

Last full run against a fresh `seed_demo` database: **156 requests, 207 tests, 0 failures**.

## Folders

| Folder | Covers |
|---|---|
| 00 Auth | Health, login for each role, refresh, profile |
| 01 School setup | Profile, settings, sessions, terms, classes, subjects, grading, assignments |
| 02 Staff | Create (temporary password), edit, assign, reset password, deactivate |
| 03 Students & guardians | CRUD, search, role-scoped views, CSV export, protected delete |
| 04 Student import | Preview and commit an Excel/CSV file |
| 05 Attendance | Register (get/save), daily summary, records, student summary |
| 06 Fees & invoices | Structures, invoice generation, adjustments, one-off invoices, cancel, pay links, reports |
| 07 Payments & receipts | Record, duplicate guard, receipts (PDF + public link), reverse |
| 08 Online payments | Parent pay page, start payment, verify, then reverse the test payment |
| 09 Results workflow | Setup, score entry, submit, return, review, approve, publish, unlock, comments |
| 10 Report cards | Class and student PDFs, share link, public link, send to guardians |
| 11 Dashboards | Principal, admin, bursar, teacher |
| 12 Audit log | Search and entry details |
| 13 Access checks | Negative tests proving the role matrix (403/401/404) |
| 99 Account & manual | Logout, password change/reset, set current term, signed Paystack webhook, clean-up |

## Variables

Set in the environment: `base_url`, `password`, `principal_email`, `admin_email`, `bursar_email`,
`teacher_email`, `paystack_secret_key` (only for the webhook example; must match the server's key).

Filled in by test scripts as you go (collection variables): `token_<role>`, `refresh_<role>`,
`term_id`, `classroom_id`, `student_id`, `invoice_id`, `payment_id`, `pay_token`, `sheet_id`, `summary_id` and others.
Requests that need a variable that isn't set yet are skipped with a console message.

## Changing the collection

Edit `tools/build_collection.py`, then regenerate (embedding real responses as examples):

```bash
node postman/tools/run_collection.mjs --collection postman/School-Ops-API.postman_collection.json \
  --environment postman/School-Ops-Local.postman_environment.json --report /tmp/run.json
python postman/tools/build_collection.py --examples /tmp/run.json
```
