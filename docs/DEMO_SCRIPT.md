# Five-minute demo script

Run `python manage.py seed_demo` first. Password for every account: **`DemoPass123!`**.
Until the frontend exists, you can run this from Swagger at `/api/docs/` (click **Authorize**
and paste the access token from `auth/login/`).

The seed builds a mid-term snapshot so every screen has something to show:

| Situation | Where |
|---|---|
| 300 students, 12 classes, 23 staff | Everywhere |
| Fees: about 60% paid, 25% part-paid, 15% owing; 3 scholarships | Bursar and principal dashboards |
| JSS 1A results **published** with comments | Report cards |
| JSS 1B results **approved**, ready to publish | Principal |
| SS 1A and SS 2A **in review**, awaiting principal approval | Principal |
| JSS 3A English and Mathematics **missing scores** | "Needs attention" |
| JSS 2A Mathematics **in draft**, 15 students without scores | Demo teacher |
| SS 3B Physics **returned** to the teacher with a note | Admin and teacher |
| JSS 2A, SS 1B and SS 3A **haven't marked attendance today** | Principal, demo teacher |

## The script

1. **Principal** (`principal@sample-school.test`): `GET dashboards/principal/`
   - Students, staff, fees collected versus outstanding, collection by class.
   - **Needs attention:** teachers with unsubmitted scores, students owing over half their fees, results waiting for approval, classes without attendance today.

2. **Teacher** (`teacher@sample-school.test`): `GET dashboards/teacher/`
   - Sees only JSS 2A as form class and Mathematics in JSS 1–2. `GET students/` returns only their students, and `GET fees/invoices/` returns **403**: teachers never see money.
   - Mark today's register: `POST attendance/register/` with one absent student.
   - Finish JSS 2A Mathematics: `GET results/sheets/`, then `PUT .../scores/`, then `POST .../submit/`.

3. **Bursar** (`bursar@sample-school.test`):
   - Record a cash payment: `POST fees/payments/` and open the receipt PDF `GET fees/payments/{id}/receipt/`.
   - Show the pay link for a parent: `GET fees/invoices/{id}/pay-link/`.

4. **Principal again:** the dashboard totals have moved (collected amount and attendance).

5. **Results:** approve SS 1A (`POST results/class-results/{id}/approve/`), publish JSS 1B
   (`.../publish/`), then open `.../report-cards/` to show the PDF for the whole class.

6. **Import:** as admin, upload `docs/samples/students_sample.csv` to
   `POST students/imports/preview/`. Show the detected columns and the report, then commit.

7. **Audit:** as principal, `GET audit/logs/` shows everything that just happened, with who and when.
