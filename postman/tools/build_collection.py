"""Build the Postman collection and environment for the School Operations Platform API.

    python postman/tools/build_collection.py                      # writes the collection + environments
    python postman/tools/build_collection.py --examples report.json  # also embeds real responses as examples

Every request:
  * logs in as the right role (bearer token from the "00 Auth" folder),
  * has a description (purpose, allowed roles, notes),
  * has test scripts that check the status and save IDs for later requests.

The whole collection can be run top to bottom (Postman Runner or postman/tools/run_collection.mjs)
against a database created with `python manage.py seed_demo`, and run again: it cleans up after itself.
"""
import argparse
import json
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent
COLLECTION_FILE = OUT_DIR / "School-Ops-API.postman_collection.json"
ENV_LOCAL = OUT_DIR / "School-Ops-Local.postman_environment.json"
ENV_STAGING = OUT_DIR / "School-Ops-Staging.postman_environment.json"

ROLE_NAMES = {"principal": "Principal", "admin": "Admin", "bursar": "Bursar", "teacher": "Teacher"}


# ---------------------------------------------------------------------------
# Script snippets
# ---------------------------------------------------------------------------
def status(*codes):
    codes_js = ", ".join(str(c) for c in codes)
    label = " or ".join(str(c) for c in codes)
    return f'pm.test("Status is {label}", () => pm.expect(pm.response.code).to.be.oneOf([{codes_js}]));'


JSON = (
    "const isJson = (pm.response.headers.get('Content-Type') || '').includes('json');\n"
    "const json = isJson && pm.response.text() ? pm.response.json() : null;"
)


def save(var, expr, when="json"):
    return f'if ({when}) {{ const v = {expr}; if (v !== undefined && v !== null) pm.collectionVariables.set("{var}", v); }}'


def skip_unless(*variables):
    checks = " || ".join(f'!pm.collectionVariables.get("{v}")' for v in variables)
    names = ", ".join(variables)
    return (
        f"if ({checks}) {{\n"
        f'  console.log("Skipping: needs {names} from an earlier request");\n'
        "  pm.execution.skipRequest();\n"
        "}"
    )


PDF_TESTS = (
    "pm.test(\"Returns a PDF\", () => pm.expect(pm.response.headers.get('Content-Type')).to.include('application/pdf'));"
)


# ---------------------------------------------------------------------------
# Item builders
# ---------------------------------------------------------------------------
def url(path, query=None):
    q = []
    for key, value, *rest in query or []:
        param = {"key": key, "value": str(value)}
        if rest:
            param["description"] = rest[0]
        if value == "":
            param["disabled"] = True  # optional parameter: shown in Postman, not sent
        q.append(param)
    enabled = [p for p in q if not p.get("disabled")]
    if path.startswith("{{"):
        # A full URL held in a variable (e.g. a signed public link)
        out = {"raw": path, "host": [path]}
        return out
    path = path.lstrip("/")
    raw = "{{base_url}}/" + path
    if enabled:
        raw += "?" + "&".join(f"{p['key']}={p['value']}" for p in enabled)
    out = {"raw": raw, "host": ["{{base_url}}"], "path": [p for p in path.split("/") if p != ""]}
    if path.endswith("/"):
        out["path"].append("")
    if q:
        out["query"] = q
    return out


def auth_for(role):
    if role is None:
        return {"type": "noauth"}
    return {"type": "bearer", "bearer": [{"key": "token", "value": "{{token_%s}}" % role, "type": "string"}]}


def request(
    name,
    method,
    path,
    *,
    role="principal",
    desc="",
    body=None,
    query=None,
    form=None,
    tests=(),
    pre=(),
    expect=(200,),
    json_tests=True,
):
    allowed = ""
    headers = []
    req = {"method": method, "header": headers, "url": url(path, query), "auth": auth_for(role)}
    if body is not None:
        headers.append({"key": "Content-Type", "value": "application/json"})
        req["body"] = {
            "mode": "raw",
            "raw": body if isinstance(body, str) else json.dumps(body, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    if form is not None:
        req["body"] = {"mode": "formdata", "formdata": form}
    as_role = f"**Runs as:** {ROLE_NAMES.get(role, 'no login (public)') if role else 'no login (public)'}"
    req["description"] = (desc.strip() + "\n\n" + as_role + allowed).strip()
    test_lines = [status(*expect)]
    if json_tests:
        test_lines.insert(0, JSON)
    test_lines += list(tests)
    events = [{"listen": "test", "script": {"type": "text/javascript", "exec": "\n".join(test_lines).split("\n")}}]
    if pre:
        events.insert(0, {"listen": "prerequest", "script": {"type": "text/javascript", "exec": "\n".join(pre).split("\n")}})
    return {"name": name, "event": events, "request": req, "response": []}


def folder(name, desc, items):
    return {"name": name, "description": desc.strip(), "item": items}


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------
def login(role):
    return request(
        f"Login as {ROLE_NAMES[role]}",
        "POST",
        "/api/v1/auth/login/",
        role=None,
        body=f'{{\n  "email": "{{{{{role}_email}}}}",\n  "password": "{{{{password}}}}"\n}}',
        desc=f"""
Log in with email and password. Returns a short-lived **access** token (30 min), a **refresh**
token (7 days, rotates on use) and the user's profile with `role` and `capabilities`.

The test script saves the tokens as `token_{role}` and `refresh_{role}`; every request in the
collection that runs as the {ROLE_NAMES[role].lower()} uses `{{{{token_{role}}}}}`.
""",
        tests=[
            save(f"token_{role}", "json.access"),
            save(f"refresh_{role}", "json.refresh"),
            save(f"{role}_user_id", "json.user && json.user.id"),
            f'pm.test("Role is {role}", () => pm.expect(json.user.role).to.eql("{role}"));',
            'pm.test("Has capabilities", () => pm.expect(json.user.capabilities.length).to.be.above(0));',
        ],
    )


def auth_folder():
    return folder(
        "00 Auth",
        """
Run this folder first: it logs in as all four demo roles and stores their tokens.
Access tokens last 30 minutes. If you start getting `401`, run this folder again.
""",
        [
            request("Health check", "GET", "/health/", role=None, desc="Uptime check. No login needed.",
                    tests=['pm.test("Status ok", () => pm.expect(json.status).to.eql("ok"));']),
            login("principal"),
            login("admin"),
            login("bursar"),
            login("teacher"),
            request(
                "Refresh access token",
                "POST",
                "/api/v1/auth/refresh/",
                role=None,
                body='{\n  "refresh": "{{refresh_bursar}}"\n}',
                desc="""
Exchange a refresh token for a new access token. Refresh tokens **rotate**: the response
contains a new refresh token and the old one stops working.
""",
                tests=[save("token_bursar", "json.access"), save("refresh_bursar", "json.refresh")],
            ),
            request(
                "My profile",
                "GET",
                "/api/v1/auth/me/",
                role="teacher",
                desc="The logged-in user's profile, role, school and capabilities. Use `capabilities` to decide which menus to show.",
                tests=['pm.test("Is the teacher", () => pm.expect(json.role).to.eql("teacher"));'],
            ),
            request(
                "Update my profile",
                "PATCH",
                "/api/v1/auth/me/",
                role="teacher",
                body={"phone": "08000000004"},
                desc="Users can change `first_name`, `last_name` and `phone`. Role and email are read-only.",
            ),
        ],
    )


def school_folder():
    return folder(
        "01 School setup",
        """
School profile and settings, academic sessions and terms, classes, subjects, grading scale and
teacher assignments.

* Read: every role (teachers see only their own classes and assignments; bursars can read classes).
* Write: admin; the principal can also edit the profile, settings, sessions, terms and grading.

Requests that create test records delete them again at the end of the folder.
""",
        [
            request("School profile", "GET", "/api/v1/school/", role="principal",
                    desc="Name, address, phone, email, motto and logo.",
                    tests=[save("school_name", "json.name")]),
            request("Update school profile", "PATCH", "/api/v1/school/", role="principal",
                    body={"motto": "Knowledge and Character"},
                    desc="Principal or admin. Changes are written to the audit log."),
            request("School settings", "GET", "/api/v1/school/settings/", role="bursar",
                    desc="Score split (`ca1_max` + `ca2_max` + `exam_max` = 100), part-payment rules, "
                         "invoice/receipt prefixes and the report-card hold for unpaid fees.",
                    tests=['pm.test("Score split adds up to 100", () => pm.expect(json.max_total).to.eql(100));']),
            request("Update school settings", "PATCH", "/api/v1/school/settings/", role="admin",
                    body={"report_card_footer": "This is a demo report card generated with fictional data."},
                    desc="Principal or admin. If you change the score maximums they must still add up to 100 (400 otherwise)."),
            request("Current term", "GET", "/api/v1/terms/current/", role="teacher",
                    desc="The term marked current. Returns 404 with `code: no_current_term` if none is set.",
                    tests=[save("term_id", "json.id"), save("session_id", "json.session")]),
            request("List terms", "GET", "/api/v1/terms/", role="admin", query=[("session", "{{session_id}}")],
                    desc="Filters: `session`, `is_current`, `name` (`first`, `second`, `third`).",
                    tests=[save("second_term_id", "(json.results.find(t => t.name === 'second') || {}).id")]),
            request("List academic sessions", "GET", "/api/v1/sessions/", role="admin"),
            request("Create academic session", "POST", "/api/v1/sessions/", role="admin",
                    pre=['pm.collectionVariables.set("temp_session_name", "Test " + Math.floor(Math.random() * 1e6));'],
                    body={"name": "{{temp_session_name}}", "start_date": "2099-09-01", "end_date": "2100-07-31"},
                    expect=(201,),
                    desc="Principal or admin. `name` must be unique per school; end date after start date.",
                    tests=[save("temp_session_id", "json.id")]),
            request("Create term", "POST", "/api/v1/terms/", role="admin",
                    body={"session": "{{temp_session_id}}", "name": "first", "start_date": "2099-09-08", "end_date": "2099-12-15"},
                    expect=(201,),
                    desc="Term dates must fall inside the session. Use **Set current term** (in *99 Account & manual*) to switch terms.",
                    tests=[save("temp_term_id", "json.id")]),
            request("List classes", "GET", "/api/v1/classes/", role="admin", query=[("page_size", "50")],
                    desc="Each class arm with `student_count` and its form (class) teacher. Filter: `level`, `class_teacher`.",
                    tests=[save("classroom_id", "json.results[0].id"),
                           'pm.test("Has classes", () => pm.expect(json.count).to.be.above(0));']),
            request("Class details", "GET", "/api/v1/classes/{{classroom_id}}/", role="principal"),
            request("Students in a class", "GET", "/api/v1/classes/{{classroom_id}}/students/", role="admin",
                    desc="Active students of the class. Principal, admin, and teachers for their own classes."),
            request("Create class arm", "POST", "/api/v1/classes/", role="admin",
                    pre=['pm.collectionVariables.set("temp_arm", "T" + Math.floor(100 + Math.random() * 900));'],
                    body={"level": "SS3", "arm": "{{temp_arm}}", "capacity": 30},
                    expect=(201,),
                    desc="Admin only. `level` is one of `JSS1` … `SS3`; `arm` is free text (A, B, Gold…). Shown as e.g. \"SS 3A\".",
                    tests=[save("temp_classroom_id", "json.id"),
                           'pm.test("Name is built from level and arm", () => pm.expect(json.name).to.include("SS 3"));']),
            request("Edit class arm", "PATCH", "/api/v1/classes/{{temp_classroom_id}}/", role="admin",
                    pre=[skip_unless("temp_classroom_id")], body={"capacity": 35, "class_teacher": None},
                    desc="`class_teacher` must be an active teacher (or null)."),
            request("Delete class arm", "DELETE", "/api/v1/classes/{{temp_classroom_id}}/", role="admin",
                    pre=[skip_unless("temp_classroom_id")], expect=(204,), json_tests=False,
                    desc="Only classes with no history. Once a class has students, attendance, invoices or results it can't be deleted (409).",
                    tests=['pm.collectionVariables.unset("temp_classroom_id");']),
            request("List subjects", "GET", "/api/v1/subjects/", role="teacher",
                    tests=[save("subject_id", "json.results[0].id")]),
            request("Create subject", "POST", "/api/v1/subjects/", role="admin",
                    pre=['pm.collectionVariables.set("temp_subject_name", "Test Subject " + Math.floor(Math.random() * 1e6));'],
                    body={"name": "{{temp_subject_name}}", "code": "TST"}, expect=(201,),
                    desc="Admin only. Names are unique per school (case-insensitive).",
                    tests=[save("temp_subject_id", "json.id")]),
            request("Grading scale", "GET", "/api/v1/grade-bands/", role="teacher",
                    desc="Default WAEC-style A1–F9. A total gets the first band (highest first) where `total >= min_score`. Not paginated.",
                    tests=['pm.test("Nine default bands", () => pm.expect(json.length).to.be.above(0));']),
            request("List teacher assignments", "GET", "/api/v1/assignments/", role="admin",
                    query=[("session", "{{session_id}}"), ("classroom", "{{classroom_id}}")],
                    desc="Who teaches which subject in which class this session. Teachers see only their own. Bursars: 403."),
            request("My assignments (teacher)", "GET", "/api/v1/assignments/", role="teacher",
                    desc="A teacher only ever sees their own assignments.",
                    tests=['pm.test("All mine", () => json.results.forEach(a => pm.expect(a.teacher).to.eql(Number(pm.collectionVariables.get("teacher_user_id")))));']),
        ],
    )


def staff_folder():
    return folder(
        "02 Staff",
        """
Staff accounts. **Admin** creates and edits staff; the **principal** can view. Bursars and teachers get 403
(teachers use *My profile*). Staff are never deleted: deactivate them instead. Admins cannot create a principal,
edit the principal, or change their own role.
""",
        [
            request("List staff", "GET", "/api/v1/staff/", role="principal", query=[("role", "teacher"), ("is_active", "true")],
                    desc="Filters: `role`, `is_active`. Search: name, email, phone. Teachers include `form_classes` and `teaching`."),
            request("Create staff (temporary password)", "POST", "/api/v1/staff/", role="admin",
                    pre=['pm.collectionVariables.set("temp_staff_email", "postman." + Date.now() + "@sample-school.test");'],
                    body={"email": "{{temp_staff_email}}", "first_name": "Postman", "last_name": "Teacher",
                          "phone": "08000009999", "role": "teacher"},
                    expect=(201,),
                    desc="""
Admin only. Leave out `password` and the API generates one, returned **once** as `temporary_password`.
The user must change it at first login (`must_change_password: true`). Role cannot be `principal`.
""",
                    tests=[save("staff_id", "json.id"),
                           'pm.test("Temporary password returned once", () => pm.expect(json.temporary_password).to.be.a("string"));',
                           'pm.test("Must change password", () => pm.expect(json.must_change_password).to.eql(true));']),
            request("Staff details", "GET", "/api/v1/staff/{{staff_id}}/", role="principal",
                    tests=['pm.test("Temporary password not shown again", () => pm.expect(json.temporary_password).to.eql(null));']),
            request("Edit staff", "PATCH", "/api/v1/staff/{{staff_id}}/", role="admin", body={"phone": "08000008888"}),
            request("Assign teacher to a subject", "POST", "/api/v1/assignments/", role="admin",
                    body={"session": "{{session_id}}", "classroom": "{{classroom_id}}", "subject": "{{temp_subject_id}}",
                          "teacher": "{{staff_id}}"},
                    expect=(201,),
                    desc="Admin only. One teacher per subject per class per session. After changing assignments, run **Results setup**.",
                    tests=[save("temp_assignment_id", "json.id")]),
            request("Remove assignment", "DELETE", "/api/v1/assignments/{{temp_assignment_id}}/", role="admin",
                    expect=(204,), json_tests=False),
            request("Reset staff password", "POST", "/api/v1/staff/{{staff_id}}/reset-password/", role="admin",
                    desc="Generates a new temporary password (returned once) and forces a change at next login.",
                    tests=['pm.test("New temporary password", () => pm.expect(json.temporary_password).to.be.a("string"));']),
            request("Deactivate staff", "POST", "/api/v1/staff/{{staff_id}}/deactivate/", role="admin",
                    desc="Blocks login. History stays intact.",
                    tests=['pm.test("Inactive", () => pm.expect(json.is_active).to.eql(false));']),
            request("Reactivate staff", "POST", "/api/v1/staff/{{staff_id}}/activate/", role="admin"),
            request("Deactivate again (clean up)", "POST", "/api/v1/staff/{{staff_id}}/deactivate/", role="admin",
                    desc="Leaves the test account inactive so repeated runs don't add active staff."),
            request("Admin cannot change the principal", "POST", "/api/v1/staff/{{principal_user_id}}/deactivate/",
                    role="admin", expect=(403,), desc="Negative test: only the platform operator can change the principal's account."),
        ],
    )


def students_folder():
    return folder(
        "03 Students & guardians",
        """
* **Admin**: full create, edit, delete.
* **Principal**: read and export.
* **Bursar**: read with basic fields only (name, admission no, class, status, guardians).
* **Teacher**: read students and guardians of their own classes only (others are 404).

Students with history (invoices, scores, attendance) cannot be deleted (409); set `status` to `withdrawn` instead.
""",
        [
            request("List students", "GET", "/api/v1/students/", role="admin",
                    query=[("page_size", "10"), ("status", "active"), ("ordering", "last_name")],
                    desc="Filters: `classroom`, `status`, `gender`, `classroom__level`. Search: names, admission number. Ordering: `last_name`, `first_name`, `admission_number`, `created_at`.",
                    tests=[save("student_id", "json.results[0].id")]),
            request("Search students", "GET", "/api/v1/students/", role="principal",
                    query=[("search", "Okafor"), ("classroom__level", "JSS2")]),
            request("Student details", "GET", "/api/v1/students/{{student_id}}/", role="principal",
                    tests=['pm.test("Full details", () => pm.expect(json).to.have.property("date_of_birth"));']),
            request("Student details as bursar (basic)", "GET", "/api/v1/students/{{student_id}}/", role="bursar",
                    desc="The bursar gets a smaller object: no date of birth or address.",
                    tests=['pm.test("Basic fields only", () => pm.expect(json).to.not.have.property("date_of_birth"));',
                           'pm.test("Includes guardians", () => pm.expect(json).to.have.property("guardians"));']),
            request("My students (teacher)", "GET", "/api/v1/students/", role="teacher",
                    desc="Only students in the teacher's form class or classes they teach.",
                    tests=['pm.test("Scoped list", () => pm.expect(json.count).to.be.below(300));']),
            request("Create guardian", "POST", "/api/v1/guardians/", role="admin",
                    body={"first_name": "Mrs Grace", "last_name": "Postman", "relationship": "Mother",
                          "phone": "08000007777", "email": "grace.postman@example.com"},
                    expect=(201,),
                    desc="Create the guardian first, then link them to students with `guardian_ids`. Siblings can share one guardian.",
                    tests=[save("guardian_id", "json.id")]),
            request("Create student", "POST", "/api/v1/students/", role="admin",
                    pre=['pm.collectionVariables.set("temp_admission", "PM/" + Date.now());'],
                    body={"admission_number": "{{temp_admission}}", "first_name": "Tobi", "middle_name": "",
                          "last_name": "Postman", "gender": "male", "date_of_birth": "2013-04-12",
                          "classroom": "{{classroom_id}}", "admission_date": "2025-09-15",
                          "guardian_ids": ["{{guardian_id}}"]},
                    expect=(201,),
                    desc="Admin only. `admission_number` must be unique in the school. Every `classroom`/`guardian_ids` value must belong to your school (400 otherwise).",
                    tests=[save("new_student_id", "json.id"),
                           'pm.test("Guardian linked", () => pm.expect(json.guardians[0].phone).to.eql("08000007777"));']),
            request("Edit student", "PATCH", "/api/v1/students/{{new_student_id}}/", role="admin",
                    body={"middle_name": "Ade", "address": "1 Test Street, Lagos"},
                    desc="Changes are written to the audit log with before/after values."),
            request("Export students (CSV)", "GET", "/api/v1/students/export/", role="principal",
                    query=[("classroom", "{{classroom_id}}")], json_tests=False,
                    desc="Principal or admin. Accepts the same filters as the list.",
                    tests=["pm.test(\"CSV\", () => pm.expect(pm.response.headers.get('Content-Type')).to.include('text/csv'));"]),
            request("List guardians", "GET", "/api/v1/guardians/", role="bursar", query=[("search", "Postman")]),
            request("Delete student (no history)", "DELETE", "/api/v1/students/{{new_student_id}}/", role="admin",
                    expect=(204,), json_tests=False,
                    desc="Allowed only for students entered by mistake. With invoices, scores or attendance you get 409 (`code: protected`)."),
            request("Delete guardian", "DELETE", "/api/v1/guardians/{{guardian_id}}/", role="admin", expect=(204,), json_tests=False),
            request("Delete student with history (409)", "DELETE", "/api/v1/students/{{student_id}}/", role="admin",
                    expect=(409,), desc="Negative test: seeded students have invoices and attendance, so deletion is refused.",
                    tests=['pm.test("Protected", () => pm.expect(json.code).to.eql("protected"));']),
        ],
    )


def import_folder():
    return folder(
        "04 Student import (Excel/CSV)",
        """
Admin only. Two steps: **preview** (nothing is saved) then **commit** (creates the valid rows).

In the Postman app, select the file for the `file` field yourself: use
`docs/samples/students_sample.csv` from the repo, or your own `.csv`/`.xlsx`.
On a second run the sample rows already exist, so the preview reports them as errors and the commit creates 0 students.
""",
        [
            request("Preview import", "POST", "/api/v1/students/imports/preview/", role="admin",
                    form=[{"key": "file", "type": "file", "src": "docs/samples/students_sample.csv",
                           "description": "A .csv or .xlsx file, max 5 MB / 5,000 rows"},
                          {"key": "column_mapping", "type": "text", "value": "", "disabled": True,
                           "description": 'Optional JSON, e.g. {"Code": "admission_number"}'}],
                    expect=(201,),
                    desc="""
Reads the file, detects the columns, validates every row and returns a report:
`column_mapping`, `unmapped_columns`, `missing_required_columns`, `total_rows`, `valid_rows`,
`error_count`, `errors` (with spreadsheet row numbers) and a `sample` of valid rows.
""",
                    tests=[save("import_id", "json.import_id"),
                           'pm.test("Detected the class column", () => pm.expect(json.column_mapping).to.have.property("classroom"));']),
            request("Commit import", "POST", "/api/v1/students/imports/{{import_id}}/commit/", role="admin",
                    pre=[skip_unless("import_id")],
                    desc="Creates the valid rows (and their guardians) in one transaction. A second commit of the same import returns 409.",
                    tests=['pm.test("Completed", () => pm.expect(json.status).to.eql("completed"));']),
            request("Import history", "GET", "/api/v1/students/imports/", role="admin"),
            request("Import details with row errors", "GET", "/api/v1/students/imports/{{import_id}}/", role="admin",
                    pre=[skip_unless("import_id")]),
        ],
    )


def attendance_folder():
    return folder(
        "05 Attendance",
        """
Teachers mark registers for their own classes (form class or classes they teach). Principal and admin
can view but not mark. Send only the absent, late or excused students; everyone else is saved as present.
""",
        [
            request("Teacher dashboard (find my class)", "GET", "/api/v1/dashboards/teacher/", role="teacher",
                    desc="Used here to find the teacher's form class.",
                    tests=[save("teacher_classroom_id", "json.form_classes[0] && json.form_classes[0].id")]),
            request("Get register", "GET", "/api/v1/attendance/register/", role="teacher",
                    query=[("classroom", "{{teacher_classroom_id}}"), ("date", "", "YYYY-MM-DD. Defaults to today")],
                    desc="Unmarked students show `status: present` with `is_marked: false`.",
                    tests=[save("absent_student_id", "json.students[0].student"),
                           save("late_student_id", "json.students[1] && json.students[1].student")]),
            request("Save register", "POST", "/api/v1/attendance/register/", role="teacher",
                    body='{\n  "classroom": {{teacher_classroom_id}},\n  "records": [\n    {"student": {{absent_student_id}}, "status": "absent", "note": "Sick"},\n    {"student": {{late_student_id}}, "status": "late"}\n  ]\n}',
                    desc="""
Saves the whole register for the day. `date` is optional (defaults to today, never in the future, must be in a term).
`status`: `present` | `absent` | `late` | `excused`. Saving again overwrites the day.
""",
                    tests=['pm.test("Marked", () => pm.expect(json.is_marked).to.eql(true));']),
            request("Principal cannot mark (403)", "POST", "/api/v1/attendance/register/", role="principal",
                    body='{\n  "classroom": {{teacher_classroom_id}}\n}', expect=(403,),
                    desc="Negative test: the principal and admin view registers but don't mark them."),
            request("Daily summary", "GET", "/api/v1/attendance/summary/", role="principal",
                    query=[("date", "", "Defaults to today")],
                    desc="Per class: marked or not, present, late, absent, excused and attendance rate, plus school totals."),
            request("Attendance records", "GET", "/api/v1/attendance/records/", role="admin",
                    query=[("classroom", "{{teacher_classroom_id}}"), ("status", "absent"), ("date_from", ""), ("date_to", "")]),
            request("Student term summary", "GET", "/api/v1/attendance/students/{{absent_student_id}}/summary/",
                    role="principal", query=[("term", "{{term_id}}")],
                    tests=['pm.test("Has totals", () => pm.expect(json).to.have.property("attendance_rate"));']),
        ],
    )


def fees_folder():
    return folder(
        "06 Fees & invoices",
        """
**Bursar** manages fee structures and invoices; the **principal** can read everything; admin and teachers get 403.

Money is always an integer in **kobo** (₦1 = 100). Invoice `total_kobo`, `amount_paid_kobo`,
`balance_kobo` and `status` (`unpaid`, `part_paid`, `paid`, `cancelled`) are calculated by the server.
""",
        [
            request("List fee structures", "GET", "/api/v1/fees/structures/", role="bursar",
                    query=[("term", "{{term_id}}")],
                    tests=[save("structure_id", "json.results[0].id")]),
            request("Fee structure details", "GET", "/api/v1/fees/structures/{{structure_id}}/", role="principal"),
            request("Generate invoices for a structure", "POST", "/api/v1/fees/structures/{{structure_id}}/generate-invoices/",
                    role="bursar", expect=(200, 201),
                    desc="Creates the term invoice for every active student at that level. Safe to run again: existing invoices are skipped (200 with `created: 0`).",
                    tests=['pm.test("Reports counts", () => pm.expect(json).to.have.property("skipped_existing"));']),
            request("Create fee structure", "POST", "/api/v1/fees/structures/", role="bursar",
                    pre=[skip_unless("second_term_id")],
                    body={"term": "{{second_term_id}}", "level": "JSS1", "name": "JSS 1 fees (second term)",
                          "due_date": None,
                          "items": [{"name": "Tuition", "amount_kobo": 15000000, "position": 0},
                                    {"name": "PTA levy", "amount_kobo": 500000, "position": 1}]},
                    expect=(201,),
                    desc="One structure per class level per term. `items` are the lines copied onto each invoice.",
                    tests=[save("temp_structure_id", "json.id"),
                           'pm.test("Total is the sum of items", () => pm.expect(json.total_kobo).to.eql(15500000));']),
            request("Edit fee structure (items replaced)", "PATCH", "/api/v1/fees/structures/{{temp_structure_id}}/", role="bursar",
                    pre=[skip_unless("temp_structure_id")],
                    body={"items": [{"name": "Tuition", "amount_kobo": 16000000}]},
                    desc="Sending `items` replaces all items."),
            request("Delete fee structure", "DELETE", "/api/v1/fees/structures/{{temp_structure_id}}/", role="bursar",
                    pre=[skip_unless("temp_structure_id")], expect=(204,), json_tests=False,
                    desc="Allowed only before invoices are generated from it (409 otherwise)."),
            request("List invoices (part-paid)", "GET", "/api/v1/fees/invoices/", role="bursar",
                    query=[("term", "{{term_id}}"), ("status", "part_paid"), ("ordering", "-balance_kobo"), ("page_size", "10")],
                    desc="Filters: `term`, `classroom`, `student`, `status`, `level`, `has_balance`. Search: invoice number, student name, admission number. Ordering: `balance_kobo`, `total_kobo`, `created_at`, `student__last_name`.",
                    tests=[save("invoice_id", "json.results[0].id"), save("invoice_student_id", "json.results[0].student")]),
            request("Students owing (has balance)", "GET", "/api/v1/fees/invoices/", role="principal",
                    query=[("has_balance", "true"), ("classroom", "{{classroom_id}}")]),
            request("Invoice details", "GET", "/api/v1/fees/invoices/{{invoice_id}}/", role="principal",
                    desc="Includes `lines`, `adjustments` and `payments`.",
                    tests=['pm.test("Balance = total - paid", () => pm.expect(json.balance_kobo).to.eql(json.total_kobo - json.amount_paid_kobo));']),
            request("Add surcharge", "POST", "/api/v1/fees/invoices/{{invoice_id}}/adjustments/", role="bursar",
                    body={"kind": "surcharge", "amount_kobo": 100000, "reason": "Late registration (Postman test)"},
                    expect=(201,),
                    desc="`kind`: `discount`, `scholarship`, `waiver` (reduce the total) or `surcharge` (adds). A discount can't exceed the total."),
            request("Add discount (cancels the surcharge)", "POST", "/api/v1/fees/invoices/{{invoice_id}}/adjustments/", role="bursar",
                    body={"kind": "discount", "amount_kobo": 100000, "reason": "Reverse Postman test surcharge"},
                    expect=(201,)),
            request("Create one-off invoice", "POST", "/api/v1/fees/invoices/", role="bursar",
                    pre=[skip_unless("second_term_id")],
                    body={"student": "{{invoice_student_id}}", "term": "{{second_term_id}}",
                          "lines": [{"description": "Excursion", "amount_kobo": 1500000}], "notes": "Postman test"},
                    expect=(201,),
                    desc="For late admissions or special charges. One open invoice per student per term (409 otherwise).",
                    tests=[save("oneoff_invoice_id", "json.id")]),
            request("Cancel invoice", "POST", "/api/v1/fees/invoices/{{oneoff_invoice_id}}/cancel/", role="bursar",
                    pre=[skip_unless("oneoff_invoice_id")],
                    body={"reason": "Created by Postman test"},
                    desc="Only invoices without payments (409 otherwise: reverse the payments first).",
                    tests=['pm.test("Cancelled", () => pm.expect(json.status).to.eql("cancelled"));']),
            request("Get parent pay link", "GET", "/api/v1/fees/invoices/{{invoice_id}}/pay-link/", role="bursar",
                    desc="`url` is `FRONTEND_URL/pay/<token>`; the frontend's pay page uses the token with the public endpoints.",
                    tests=[save("pay_url", "json.url"), save("pay_token", "json.url.split('/pay/')[1]")]),
            request("Send pay link to guardians", "POST", "/api/v1/fees/invoices/{{invoice_id}}/send-pay-link/", role="bursar",
                    expect=(200, 400),
                    desc="SMS and email to the student's guardians (console SMS backend in development). 400 if no guardian contact."),
            request("Outstanding by class", "GET", "/api/v1/fees/reports/outstanding/", role="principal",
                    query=[("term", "{{term_id}}")],
                    tests=['pm.test("Has totals", () => pm.expect(json.totals).to.have.property("outstanding_kobo"));']),
            request("Collections by day and method", "GET", "/api/v1/fees/reports/collections/", role="bursar",
                    query=[("date_from", ""), ("date_to", "")],
                    desc="Defaults to the 1st of this month up to today."),
            request("Admin cannot see fees (403)", "GET", "/api/v1/fees/invoices/", role="admin", expect=(403,)),
        ],
    )


def payments_folder():
    return folder(
        "07 Payments & receipts",
        """
**Bursar** records money received (cash, bank transfer, POS, cheque) and can reverse a payment; the **principal** reads.
Payments are never edited or deleted. A reversal is a new negative payment linked to the original.
Each successful payment gets a numbered receipt (`RCT-000123`).
""",
        [
            request("Record a payment", "POST", "/api/v1/fees/payments/", role="bursar",
                    pre=['pm.collectionVariables.set("teller_ref", "PM" + Date.now());'],
                    body={"invoice": "{{invoice_id}}", "amount_kobo": 500000, "method": "bank_transfer",
                          "external_reference": "{{teller_ref}}", "payer_name": "Mrs Grace Postman",
                          "note": "Postman test payment"},
                    expect=(201,),
                    desc="""
`method`: `cash` | `bank_transfer` | `pos` | `cheque` (online payments are recorded automatically).
`amount_kobo` can't exceed the balance. The same bank/teller reference can't be recorded twice (409).
Optional `paid_at` (not in the future).
""",
                    tests=[save("payment_id", "json.id"),
                           'pm.test("Receipt issued", () => pm.expect(json.receipt_number).to.include("RCT-"));']),
            request("Duplicate bank reference (409)", "POST", "/api/v1/fees/payments/", role="bursar",
                    body={"invoice": "{{invoice_id}}", "amount_kobo": 100, "method": "bank_transfer",
                          "external_reference": "{{teller_ref}}"},
                    expect=(409,), desc="Negative test: protects against recording the same transfer twice."),
            request("List payments", "GET", "/api/v1/fees/payments/", role="principal",
                    query=[("method", "bank_transfer"), ("date_from", ""), ("ordering", "-paid_at"), ("page_size", "10")],
                    desc="Filters: `invoice`, `student`, `method`, `status`, `term`, `classroom`, `date_from`, `date_to`."),
            request("Payment details", "GET", "/api/v1/fees/payments/{{payment_id}}/", role="bursar"),
            request("Receipt PDF", "GET", "/api/v1/fees/payments/{{payment_id}}/receipt/", role="bursar", json_tests=False,
                    tests=[PDF_TESTS]),
            request("Receipt link for parents", "GET", "/api/v1/fees/payments/{{payment_id}}/receipt-link/", role="bursar",
                    desc="Signed link, valid for 180 days by default. Opens the PDF without login.",
                    tests=[save("receipt_url", "json.url")]),
            request("Open public receipt link", "GET", "{{receipt_url}}", role=None, json_tests=False,
                    desc="What the parent sees: the receipt PDF, no login.",
                    tests=[PDF_TESTS]),
            request("Send receipt to guardians", "POST", "/api/v1/fees/payments/{{payment_id}}/send-receipt/", role="bursar"),
            request("Reverse payment", "POST", "/api/v1/fees/payments/{{payment_id}}/reverse/", role="bursar",
                    body={"reason": "Postman test: entered in error"}, expect=(201,),
                    desc="Creates a negative payment; the invoice balance goes back up. A payment can only be reversed once (409).",
                    tests=['pm.test("Negative amount", () => pm.expect(json.amount_kobo).to.be.below(0));']),
            request("Principal cannot record payments (403)", "POST", "/api/v1/fees/payments/", role="principal",
                    body={"invoice": "{{invoice_id}}", "amount_kobo": 100, "method": "cash"}, expect=(403,)),
        ],
    )


def online_folder():
    return folder(
        "08 Online payments (parent, public)",
        """
The parent pay flow. These endpoints need **no login**: they use the signed token from the pay link.

1. **Invoice summary** for the pay page.
2. **Start payment** returns a Paystack `authorization_url`; the frontend redirects the parent there.
3. Paystack sends the parent back to `PAYSTACK_CALLBACK_URL?reference=...`; the page calls **Verify payment**.

Without Paystack keys, set `PAYSTACK_SIMULATE=true` (with `DJANGO_DEBUG=true`) so payments complete instantly.
If online payments aren't configured, *Start payment* returns 503 and the next requests are skipped.
The last request reverses the test payment so the demo data stays the same.
""",
        [
            request("Invoice summary (pay page)", "GET", "/api/v1/public/pay/{{pay_token}}/", role=None,
                    pre=[skip_unless("pay_token")],
                    tests=['pm.test("Has balance", () => pm.expect(json).to.have.property("balance_kobo"));',
                           save("online_amount", "Math.min(json.balance_kobo, Math.max(json.minimum_part_payment_kobo, 100000))")]),
            request("Start online payment", "POST", "/api/v1/public/pay/{{pay_token}}/initialize/", role=None,
                    pre=[skip_unless("pay_token", "online_amount")],
                    body='{\n  "email": "parent@example.com",\n  "amount_kobo": {{online_amount}},\n  "payer_name": "Mrs Grace Postman"\n}',
                    expect=(201, 503),
                    desc="""
Creates a pending payment and returns `authorization_url`, `access_code`, `reference` and `public_key`.
`amount_kobo` is optional (defaults to the full balance); part payments follow the school's rules
(`allow_part_payment`, `minimum_part_payment_kobo`). 503 = online payments not set up.
""",
                    tests=['if (pm.response.code === 201) { pm.collectionVariables.set("online_reference", json.reference); }',
                           'else { pm.collectionVariables.unset("online_reference"); }']),
            request("Verify payment (callback page)", "GET", "/api/v1/public/payments/verify/", role=None,
                    pre=[skip_unless("online_reference")],
                    query=[("reference", "{{online_reference}}")],
                    desc="Asks Paystack for the result (works even if the webhook is late). Returns `status`, `receipt_number`, `receipt_url` and the new `invoice_balance_kobo`.",
                    tests=['pm.test("Has a status", () => pm.expect(["successful", "pending", "failed"]).to.include(json.status));']),
            request("Find the online payment", "GET", "/api/v1/fees/payments/", role="bursar",
                    pre=[skip_unless("online_reference")],
                    query=[("search", "{{online_reference}}")],
                    tests=[save("online_payment_id", "json.results[0] && json.results[0].status === 'successful' ? json.results[0].id : undefined")]),
            request("Reverse the test online payment", "POST", "/api/v1/fees/payments/{{online_payment_id}}/reverse/",
                    role="bursar", pre=[skip_unless("online_payment_id")],
                    body={"reason": "Postman test online payment"}, expect=(201,),
                    tests=['pm.collectionVariables.unset("online_payment_id");']),
        ],
    )


def results_folder():
    teacher_pick = """if (json) {
  const pick = json.results.find(s => s.class_result_status === 'open' && s.status !== 'submitted') || json.results[0];
  if (pick) pm.collectionVariables.set("sheet_id", pick.id);
}"""
    build_scores = """if (json && json.rows) {
  // Keep existing scores and fill any gaps so the sheet can be submitted.
  const scores = json.rows.map(r => ({
    student: r.student,
    ca1: r.ca1 === null ? 12 : Number(r.ca1),
    ca2: r.ca2 === null ? 13 : Number(r.ca2),
    exam: r.exam === null ? 41 : Number(r.exam),
  }));
  pm.collectionVariables.set("score_payload", JSON.stringify({ scores: scores }, null, 2));
  pm.test("One row per student", () => pm.expect(json.rows.length).to.be.above(0));
}"""
    pick_classes = """if (json) {
  const byStatus = s => (json.results.find(r => r.status === s) || {}).id;
  ["in_review", "approved", "published", "open"].forEach(s => {
    const id = byStatus(s);
    if (id) pm.collectionVariables.set("class_result_" + s, id); else pm.collectionVariables.unset("class_result_" + s);
  });
}"""
    return folder(
        "09 Results workflow",
        """
Score sheets, the approval workflow and comments.

```
Sheet:  draft → submitted (teacher) → returned (admin, with note) → submitted …
Class:  open → in_review (admin) → approved (principal) → published (principal)
        published → in_review (principal unlock, reason required)
```

Wrong-state actions return **409** with a message; tests accept that where a re-run can hit it.
The workflow requests use a class that is *in review* in the seed data and put it back at the end.
""",
        [
            request("Results setup for the term", "POST", "/api/v1/results/setup/", role="admin",
                    body={"term": "{{term_id}}"},
                    desc="Admin. Creates class results and score sheets from teacher assignments. Idempotent: run again after changing assignments."),
            request("My score sheets (teacher)", "GET", "/api/v1/results/sheets/", role="teacher",
                    query=[("term", "{{term_id}}")],
                    desc="Teachers see only their sheets, each with `progress` (`students`, `complete`, `missing`).",
                    tests=[teacher_pick]),
            request("Score sheet with student rows", "GET", "/api/v1/results/sheets/{{sheet_id}}/", role="teacher",
                    desc="One `row` per student with CA1, CA2, exam, total, grade and remark; `maxima` and `can_edit` for the UI.",
                    tests=[build_scores]),
            request("Save scores", "PUT", "/api/v1/results/sheets/{{sheet_id}}/scores/", role="teacher",
                    body="{{score_payload}}", expect=(200, 409),
                    desc="""
Subject teacher only. Send any subset of students and fields; `null` clears a score; decimals allowed.
The server checks maximums (default 20/20/60) and calculates total, grade and remark.
409 when the sheet is submitted or the class is past `open`.
"""),
            request("Submit sheet", "POST", "/api/v1/results/sheets/{{sheet_id}}/submit/", role="teacher",
                    expect=(200, 400, 409),
                    desc="Every student needs all three scores (400 otherwise). Locks the sheet."),
            request("Return sheet to teacher (admin)", "POST", "/api/v1/results/sheets/{{sheet_id}}/return/", role="admin",
                    body={"note": "Please double-check the exam scores (Postman test)."}, expect=(200, 409),
                    desc="Admin. Only submitted sheets. If the class was in review it goes back to `open`."),
            request("Resubmit after correction", "POST", "/api/v1/results/sheets/{{sheet_id}}/submit/", role="teacher",
                    expect=(200, 400, 409)),
            request("Teacher sees only their own sheets", "GET", "/api/v1/results/sheets/",
                    role="teacher", query=[("teacher", "{{admin_user_id}}")],
                    desc="Filtering by anyone else returns an empty list: teachers only ever see their own sheets.",
                    tests=['pm.test("Nothing visible", () => pm.expect(json.count).to.eql(0));']),
            request("Missing scores tracker", "GET", "/api/v1/results/missing/", role="principal",
                    query=[("term", "{{term_id}}")],
                    desc="Unsubmitted sheets with missing counts, grouped by teacher. Feeds the principal's \"needs attention\" list."),
            request("Class results", "GET", "/api/v1/results/class-results/", role="admin",
                    query=[("term", "{{term_id}}"), ("page_size", "50")],
                    desc="Each class's workflow `status`, `sheets_total`/`sheets_submitted` and class average.",
                    tests=[pick_classes]),
            request("Begin review (admin)", "POST", "/api/v1/results/class-results/{{class_result_open}}/begin-review/",
                    role="admin", pre=[skip_unless("class_result_open")], expect=(200, 400, 409),
                    desc="Admin. Needs every sheet in the class submitted (400 otherwise). Calculates totals and positions."),
            request("Summaries (positions)", "GET", "/api/v1/results/class-results/{{class_result_in_review}}/summaries/",
                    role="principal", pre=[skip_unless("class_result_in_review")],
                    desc="Each student's total, average, position (ties share a position) and comments.",
                    tests=[save("review_summary_id", "json[0] && json[0].id")]),
            request("Broadsheet", "GET", "/api/v1/results/class-results/{{class_result_in_review}}/broadsheet/",
                    role="admin", pre=[skip_unless("class_result_in_review")],
                    desc="Every student's total in every subject."),
            request("Principal's comment", "PATCH", "/api/v1/results/summaries/{{review_summary_id}}/", role="principal",
                    pre=[skip_unless("review_summary_id")],
                    body={"principal_comment": "A good result. Keep working hard."},
                    desc="Principal writes `principal_comment`; the form teacher writes `class_teacher_comment`. Not allowed once published (409)."),
            request("Approve (principal)", "POST", "/api/v1/results/class-results/{{class_result_in_review}}/approve/",
                    role="principal", pre=[skip_unless("class_result_in_review")],
                    tests=['pm.test("Approved", () => pm.expect(json.status).to.eql("approved"));']),
            request("Admin cannot approve (403)", "POST", "/api/v1/results/class-results/{{class_result_in_review}}/approve/",
                    role="admin", pre=[skip_unless("class_result_in_review")], expect=(403,)),
            request("Send back to review (principal)", "POST", "/api/v1/results/class-results/{{class_result_in_review}}/send-back/",
                    role="principal", pre=[skip_unless("class_result_in_review")],
                    desc="approved → in_review, e.g. so the admin can return a sheet."),
            request("Approve again", "POST", "/api/v1/results/class-results/{{class_result_in_review}}/approve/",
                    role="principal", pre=[skip_unless("class_result_in_review")]),
            request("Set next term date", "PATCH", "/api/v1/results/class-results/{{class_result_in_review}}/",
                    role="admin", pre=[skip_unless("class_result_in_review")],
                    body={"next_term_begins": "2027-01-11"}, desc="Printed on report cards."),
            request("Publish (principal)", "POST", "/api/v1/results/class-results/{{class_result_in_review}}/publish/",
                    role="principal", pre=[skip_unless("class_result_in_review")],
                    desc="Report cards become available to parents.",
                    tests=['pm.test("Published", () => pm.expect(json.status).to.eql("published"));']),
            request("Comment after publish (409)", "PATCH", "/api/v1/results/summaries/{{review_summary_id}}/", role="principal",
                    pre=[skip_unless("review_summary_id")], body={"principal_comment": "Too late"}, expect=(409,)),
            request("Unlock published results (principal)", "POST", "/api/v1/results/class-results/{{class_result_in_review}}/unlock/",
                    role="principal", pre=[skip_unless("class_result_in_review")],
                    body={"reason": "Postman test: reopen to correct a score"},
                    desc="published → in_review. `reason` is required and written to the audit log. (This also puts the demo class back where it started.)",
                    tests=['pm.test("Back in review", () => pm.expect(json.status).to.eql("in_review"));']),
        ],
    )


def report_cards_folder():
    return folder(
        "10 Report cards",
        """
PDF report cards: one page per student. Before publishing they carry a "DRAFT - NOT PUBLISHED" watermark.
Parents get a signed link (14 days by default). If the school holds report cards for unpaid fees,
the public link returns 403 while the term invoice has a balance.
""",
        [
            request("Published class", "GET", "/api/v1/results/class-results/", role="principal",
                    query=[("status", "published"), ("term", "{{term_id}}")],
                    tests=[save("published_class_result_id", "json.results[0] && json.results[0].id")]),
            request("Whole-class report cards (PDF)", "GET", "/api/v1/results/class-results/{{published_class_result_id}}/report-cards/",
                    role="admin", pre=[skip_unless("published_class_result_id")], json_tests=False,
                    desc="Principal or admin. One PDF for the class, sorted by name.", tests=[PDF_TESTS]),
            request("Student summaries", "GET", "/api/v1/results/class-results/{{published_class_result_id}}/summaries/",
                    role="principal", pre=[skip_unless("published_class_result_id")],
                    tests=[save("summary_id", "json[0] && json[0].id")]),
            request("One student's report card (PDF)", "GET", "/api/v1/results/summaries/{{summary_id}}/report-card/",
                    role="principal", pre=[skip_unless("summary_id")], json_tests=False, tests=[PDF_TESTS]),
            request("Share link for parents", "GET", "/api/v1/results/summaries/{{summary_id}}/share-link/", role="admin",
                    pre=[skip_unless("summary_id")], desc="Published results only (409 otherwise).",
                    tests=[save("report_card_url", "json.url")]),
            request("Open public report card link", "GET", "{{report_card_url}}", role=None, json_tests=False,
                    pre=[skip_unless("report_card_url")], expect=(200, 403),
                    desc="What the parent sees. 403 if `hold_report_cards_for_debtors` is on and fees are owed.",
                    tests=["if (pm.response.code === 200) { " + PDF_TESTS + " }"]),
            request("Send report cards to guardians", "POST",
                    "/api/v1/results/class-results/{{published_class_result_id}}/send-report-cards/", role="principal",
                    pre=[skip_unless("published_class_result_id")],
                    desc="Sends each guardian their child's link by SMS/email."),
            request("Bursar has no access to results (403)", "GET", "/api/v1/results/class-results/", role="bursar", expect=(403,)),
        ],
    )


def dashboards_folder():
    return folder(
        "11 Dashboards",
        "One dashboard per role. The principal can also open the admin and bursar dashboards.",
        [
            request("Principal dashboard", "GET", "/api/v1/dashboards/principal/", role="principal",
                    desc="Counts, fees, today's attendance, results progress, **needs_attention** (with `severity`, `type`, `message`, `link`), recent payments, staff activity.",
                    tests=['pm.test("Has needs_attention", () => pm.expect(json).to.have.property("needs_attention"));']),
            request("Admin dashboard", "GET", "/api/v1/dashboards/admin/", role="admin",
                    desc="Setup gaps, results ready for review, returned sheets, recent student changes and imports."),
            request("Bursar dashboard", "GET", "/api/v1/dashboards/bursar/", role="bursar",
                    desc="Today / this week / this month collections, outstanding by class, top debtors, pending online payments."),
            request("Teacher dashboard", "GET", "/api/v1/dashboards/teacher/", role="teacher",
                    desc="Form classes, attendance to mark today, teaching assignments, score sheets with progress, returned sheets, comments pending."),
            request("Teacher cannot open principal dashboard (403)", "GET", "/api/v1/dashboards/principal/",
                    role="teacher", expect=(403,)),
        ],
    )


def audit_folder():
    return folder(
        "12 Audit log",
        "Append-only record of who did what, when and from where. **Principal only.**",
        [
            request("Search audit log", "GET", "/api/v1/audit/logs/", role="principal",
                    query=[("action", "payment", "Prefix match, e.g. payment, results, student"), ("date_from", ""), ("page_size", "20")],
                    desc="Filters: `actor`, `actor_role`, `action` (prefix), `object_type`, `object_id`, `date_from`, `date_to`. Search: object, email, action.",
                    tests=[save("audit_id", "json.results[0] && json.results[0].id")]),
            request("Audit entry", "GET", "/api/v1/audit/logs/{{audit_id}}/", role="principal", pre=[skip_unless("audit_id")],
                    desc="`changes` holds before/after values; `metadata` holds action details."),
            request("Admin cannot read the audit log (403)", "GET", "/api/v1/audit/logs/", role="admin", expect=(403,)),
        ],
    )


def access_folder():
    checks = [
        ("Teacher → invoices", "teacher", "/api/v1/fees/invoices/", 403),
        ("Teacher → staff list", "teacher", "/api/v1/staff/", 403),
        ("Teacher → audit log", "teacher", "/api/v1/audit/logs/", 403),
        ("Bursar → score sheets", "bursar", "/api/v1/results/sheets/", 403),
        ("Bursar → staff list", "bursar", "/api/v1/staff/", 403),
        ("Bursar → teacher assignments", "bursar", "/api/v1/assignments/", 403),
        ("Admin → payments", "admin", "/api/v1/fees/payments/", 403),
        ("Principal → student imports", "principal", "/api/v1/students/imports/", 403),
        ("Principal → teacher dashboard", "principal", "/api/v1/dashboards/teacher/", 403),
    ]
    items = [request(f"{label} ({code})", "GET", path, role=role, expect=(code,),
                     desc="Negative test: this role is not allowed here.") for label, role, path, code in checks]
    items.append(request("No token (401)", "GET", "/api/v1/students/", role=None, expect=(401,),
                         desc="Every non-public endpoint needs `Authorization: Bearer <access token>`."))
    items.append(request("Teacher → student outside their classes (404)", "GET", "/api/v1/students/{{student_id}}/",
                         role="teacher", expect=(200, 404),
                         desc="Records outside a teacher's classes look like they don't exist (404). 200 only if this student happens to be in the teacher's classes."))
    return folder("13 Access checks (negative tests)",
                  "Quick proof of the role matrix: every request here should be refused.", items)


def manual_folder():
    webhook_pre = """// Signs the body like Paystack does: HMAC-SHA512 of the raw body with your secret key.
const body = pm.variables.replaceIn(pm.request.body.raw);
const secret = pm.variables.get("paystack_secret_key") || "not-set";
const signature = CryptoJS.HmacSHA512(body, secret).toString(CryptoJS.enc.Hex);
pm.request.headers.upsert({ key: "x-paystack-signature", value: signature });"""
    webhook_body = """{
  "event": "charge.success",
  "data": {
    "reference": "{{online_reference}}",
    "status": "success",
    "amount": 2000000,
    "currency": "NGN",
    "channel": "card",
    "id": 1234567890,
    "paid_at": "2026-10-01T10:00:00.000Z",
    "gateway_response": "Successful"
  }
}"""
    return folder(
        "99 Account & manual",
        """
Safe to run, but mostly useful one at a time:
logout, password change (changed and changed back), password reset, switching the current term,
and a signed Paystack webhook (set `paystack_secret_key` in the environment to the same value as the server's
`PAYSTACK_SECRET_KEY`; otherwise the server rejects it with 400).
""",
        [
            request("Login (for logout test)", "POST", "/api/v1/auth/login/", role=None,
                    body='{\n  "email": "{{bursar_email}}",\n  "password": "{{password}}"\n}',
                    tests=[save("logout_refresh", "json.refresh"), save("logout_access", "json.access")]),
            {**request("Logout", "POST", "/api/v1/auth/logout/", role="bursar",
                       body='{\n  "refresh": "{{logout_refresh}}"\n}', expect=(205,), json_tests=False,
                       desc="Blacklists the refresh token. The access token keeps working until it expires (max 30 min), so drop both on the client.")},
            request("Refresh after logout fails (401)", "POST", "/api/v1/auth/refresh/", role=None,
                    body='{\n  "refresh": "{{logout_refresh}}"\n}', expect=(401,)),
            request("Change password", "POST", "/api/v1/auth/change-password/", role="teacher",
                    body='{\n  "current_password": "{{password}}",\n  "new_password": "Temp-Postman-Pass-1"\n}',
                    desc="Also clears `must_change_password`."),
            request("Change password back", "POST", "/api/v1/auth/change-password/", role="teacher",
                    body='{\n  "current_password": "Temp-Postman-Pass-1",\n  "new_password": "{{password}}"\n}'),
            request("Request password reset email", "POST", "/api/v1/auth/password-reset/", role=None,
                    body='{\n  "email": "{{admin_email}}"\n}',
                    desc="Always 200 (doesn't reveal whether the email exists). The email links to `FRONTEND_URL/reset-password?uid=...&token=...`."),
            request("Confirm password reset", "POST", "/api/v1/auth/password-reset/confirm/", role=None,
                    body='{\n  "uid": "paste-uid-from-email",\n  "token": "paste-token-from-email",\n  "new_password": "A-New-Strong-Pass-9"\n}',
                    expect=(200, 400),
                    desc="Paste `uid` and `token` from the reset email (printed in the server console in development). With the placeholders you get 400."),
            request("Set current term", "POST", "/api/v1/terms/{{term_id}}/set-current/", role="principal",
                    desc="Principal or admin. Also makes the term's session current. (Run here on the already-current term, so nothing changes.)"),
            request("Delete test session (clean up)", "DELETE", "/api/v1/sessions/{{temp_session_id}}/", role="admin",
                    pre=[skip_unless("temp_session_id")], expect=(204,), json_tests=False,
                    tests=['pm.collectionVariables.unset("temp_session_id");']),
            request("Delete test subject (clean up)", "DELETE", "/api/v1/subjects/{{temp_subject_id}}/", role="admin",
                    pre=[skip_unless("temp_subject_id")], expect=(204,), json_tests=False,
                    tests=['pm.collectionVariables.unset("temp_subject_id");']),
            request("Paystack webhook (signed example)", "POST", "/api/v1/payments/paystack/webhook/", role=None,
                    pre=[webhook_pre], body=webhook_body, expect=(200, 400),
                    desc="""
Called by Paystack, not the frontend. The pre-request script signs the body with `paystack_secret_key`.
Processing is idempotent: a repeated event for an already-successful payment changes nothing.
Configure the real URL in the Paystack dashboard: `https://<api-domain>/api/v1/payments/paystack/webhook/`.
"""),
        ],
    )


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
RUNTIME_VARS = [
    "token_principal", "token_admin", "token_bursar", "token_teacher",
    "refresh_principal", "refresh_admin", "refresh_bursar", "refresh_teacher",
    "principal_user_id", "admin_user_id", "bursar_user_id", "teacher_user_id",
    "term_id", "session_id", "second_term_id", "classroom_id", "subject_id", "student_id",
    "teacher_classroom_id", "invoice_id", "invoice_student_id", "payment_id", "pay_token",
    "sheet_id", "summary_id", "published_class_result_id",
]

DESCRIPTION = """
# School Operations Platform API (V1)

Every endpoint of the V1 backend, organised by module, with descriptions, example bodies,
role-based logins, chained variables and test scripts.

## Quick start

1. Start the backend with demo data:
   ```
   python manage.py migrate && python manage.py seed_demo && python manage.py runserver
   ```
2. Import this collection and the **School Ops – Local** environment, then select the environment.
3. Run **00 Auth** (logs in as principal, admin, bursar and teacher; tokens are saved automatically).
4. Use any request, or run the whole collection with the Runner. It is designed to run top to bottom
   on the seed data, and it is safe to run again: test records are cleaned up and workflow changes are reversed.

## Conventions

* Base URL: `{{base_url}}` (default `http://localhost:8000`).
* Auth: Bearer JWT. Each request uses the token of the role shown in its description
  (`{{token_principal}}`, `{{token_admin}}`, `{{token_bursar}}`, `{{token_teacher}}`). Access tokens last 30 minutes;
  run **00 Auth** again if you get `401`.
* Money: integers in **kobo** (₦1 = 100).
* Lists: `{count, next, previous, results}` with `page`, `page_size`, `search`, `ordering`.
* Errors: `400` validation (field errors), `401` no/expired token, `403` role not allowed,
  `404` not found or outside your scope, `409` wrong workflow state.
* IDs flow between requests through collection variables (e.g. *List students* saves `student_id`).

## Roles

| Role | Demo login |
|---|---|
| Principal | `principal@sample-school.test` |
| Admin | `admin@sample-school.test` |
| Bursar | `bursar@sample-school.test` |
| Teacher | `teacher@sample-school.test` (form teacher of JSS 2A) |

Password for all: `DemoPass123!`. Full docs: `docs/` in the repository and `{{base_url}}/api/docs/`.
"""


def build():
    items = [
        auth_folder(), school_folder(), staff_folder(), students_folder(), import_folder(), attendance_folder(),
        fees_folder(), payments_folder(), online_folder(), results_folder(), report_cards_folder(),
        dashboards_folder(), audit_folder(), access_folder(), manual_folder(),
    ]
    variables = [
        {"key": "base_url", "value": "http://localhost:8000", "type": "string"},
        {"key": "password", "value": "DemoPass123!", "type": "string"},
        {"key": "principal_email", "value": "principal@sample-school.test", "type": "string"},
        {"key": "admin_email", "value": "admin@sample-school.test", "type": "string"},
        {"key": "bursar_email", "value": "bursar@sample-school.test", "type": "string"},
        {"key": "teacher_email", "value": "teacher@sample-school.test", "type": "string"},
        {"key": "paystack_secret_key", "value": "", "type": "string"},
    ] + [{"key": k, "value": "", "type": "string"} for k in RUNTIME_VARS]
    return {
        "info": {
            "_postman_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "school-ops-api-v1")),
            "name": "School Operations Platform API (V1)",
            "description": DESCRIPTION.strip(),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
        "event": [
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [
                        "// Collection-wide: point people to the fix for expired tokens.",
                        "if (pm.response.code === 401 && !pm.info.requestName.includes('401')) {",
                        "  console.warn('401 on ' + pm.info.requestName + ': run \"00 Auth\" again to refresh tokens.');",
                        "}",
                    ],
                },
            }
        ],
        "variable": variables,
    }


def environment(name, base_url, extra=None):
    values = [
        ("base_url", base_url, "default"),
        ("password", "DemoPass123!", "secret"),
        ("principal_email", "principal@sample-school.test", "default"),
        ("admin_email", "admin@sample-school.test", "default"),
        ("bursar_email", "bursar@sample-school.test", "default"),
        ("teacher_email", "teacher@sample-school.test", "default"),
        ("paystack_secret_key", "", "secret"),
    ] + (extra or [])
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)),
        "name": name,
        "values": [{"key": k, "value": v, "type": t, "enabled": True} for k, v, t in values],
        "_postman_variable_scope": "environment",
    }


# ---------------------------------------------------------------------------
# Examples from a real run
# ---------------------------------------------------------------------------
def _trim(body):
    if isinstance(body, dict):
        for secret in ("access", "refresh", "temporary_password"):
            if isinstance(body.get(secret), str):
                body = {**body, secret: body[secret][:12] + "...(redacted)"}
    if isinstance(body, dict) and isinstance(body.get("results"), list):
        body = {**body, "results": body["results"][:2]}
    for key in ("staff_activity", "recent_payments", "classes", "students", "rows", "pending", "top_debtors", "errors", "sample"):
        if isinstance(body, dict) and isinstance(body.get(key), list) and len(body[key]) > 3:
            body = {**body, key: body[key][:3]}
    if isinstance(body, dict) and isinstance(body.get("fees"), dict) and isinstance(body["fees"].get("classes"), list):
        body = {**body, "fees": {**body["fees"], "classes": body["fees"]["classes"][:3]}}
    if isinstance(body, list) and len(body) > 3:
        body = body[:3]
    return body


def attach_examples(collection, report):
    by_name = {}
    for entry in report.get("executions", []):
        by_name.setdefault(entry["path"], entry)

    def walk(items, prefix):
        for item in items:
            path = f"{prefix}/{item['name']}"
            if "item" in item:
                walk(item["item"], path)
                continue
            entry = by_name.get(path)
            if not entry or entry.get("skipped") or not entry.get("response"):
                continue
            res = entry["response"]
            content_type = res.get("contentType", "")
            if "json" in content_type and res.get("body"):
                try:
                    body = json.dumps(_trim(json.loads(res["body"])), indent=2, ensure_ascii=False)
                except ValueError:
                    body = res["body"]
                language = "json"
            elif "pdf" in content_type:
                body, language = "<PDF binary content>", "text"
            else:
                body, language = (res.get("body") or "")[:1500], "text"
            original = json.loads(json.dumps(item["request"]))
            item["response"] = [{
                "name": f"{res['code']} {res.get('status', '')}".strip(),
                "originalRequest": original,
                "status": res.get("status", ""),
                "code": res["code"],
                "_postman_previewlanguage": language,
                "header": [{"key": "Content-Type", "value": content_type}] if content_type else [],
                "body": body,
            }]

    walk(collection["item"], "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples", help="JSON report from run_collection.mjs to embed as examples")
    args = parser.parse_args()
    collection = build()
    if args.examples:
        attach_examples(collection, json.loads(Path(args.examples).read_text()))
    COLLECTION_FILE.write_text(json.dumps(collection, indent=2, ensure_ascii=False) + "\n")
    ENV_LOCAL.write_text(json.dumps(environment("School Ops – Local", "http://localhost:8000"), indent=2) + "\n")
    ENV_STAGING.write_text(json.dumps(environment("School Ops – Staging (template)", "https://api.example.com"), indent=2) + "\n")
    count = sum(1 for _ in _iter_requests(collection["item"]))
    print(f"Wrote {COLLECTION_FILE.name} ({count} requests) and 2 environments")


def _iter_requests(items):
    for item in items:
        if "item" in item:
            yield from _iter_requests(item["item"])
        else:
            yield item


if __name__ == "__main__":
    main()
