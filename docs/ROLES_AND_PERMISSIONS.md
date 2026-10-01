# Roles and permissions

## The four roles

| Role | Who | In one line |
|---|---|---|
| `principal` | Principal or proprietor | Sees everything, approves and publishes results, reads the audit log |
| `admin` | School administrator | Runs the school's records: students, staff, classes, imports, results review |
| `bursar` | Bursar / accounts | Owns fees and payments; sees only basic student details |
| `teacher` | Subject and form teachers | Sees only their own classes; marks attendance and enters scores |

There is also a **platform superuser** (`createsuperuser`). It is not tied to a school, can
use Django admin, and **cannot log into the API**.

## Access matrix

✓ = full access, **R** = read-only, **own** = only their own classes/subjects, blank = no access.

| Resource | Principal | Admin | Bursar | Teacher |
|---|:-:|:-:|:-:|:-:|
| School profile and settings | ✓ | ✓ | R | R |
| Sessions, terms, subjects, grade bands | ✓ (sessions/terms/grades), R (subjects) | ✓ | R | R |
| Classes | R | ✓ | R | own (R) |
| Teacher assignments | R | ✓ | | own (R) |
| Staff accounts | R | ✓ (not the principal) | | own profile via `/auth/me/` |
| Students | R + export | ✓ + import + export | R (basic fields) | own classes (R) |
| Guardians | R | ✓ | R | own classes (R) |
| Attendance registers | R | R | | mark own classes |
| Fee structures, invoices | R | | ✓ | |
| Payments, receipts | R | | record + reverse | |
| Fee reports | R | | ✓ | |
| Score sheets | R | R + return to teacher | | enter + submit own |
| Class results workflow | approve, send back, publish, unlock | set up, begin review | | R (form teacher) |
| Comments | principal's comment | | | class teacher's comment (form teacher) |
| Report cards (PDF) | ✓ + share/send | ✓ + share/send | | own form class (single) |
| Audit log | R | | | |
| Dashboards | principal, admin, bursar | admin | bursar | teacher |

**Deliberate small additions to the original plan:**
* The bursar can **read classes** (names and levels) because fee structures and filters need them. The bursar still cannot see teacher assignments.
* The principal can open the admin and bursar dashboards, since the principal sees everything.
* Teachers can only mark attendance for classes where they are the form teacher or have a subject assignment. Admins and principals can view registers but not mark them, as the matrix specifies.

## How it is enforced

### 1. Role check on every request (`apps/core/permissions.py`)

Every view declares its roles:

```python
class StudentViewSet(SchoolModelViewSet):
    read_roles = (PRINCIPAL, ADMIN, BURSAR, TEACHER)   # GET, HEAD, OPTIONS
    write_roles = (ADMIN,)                             # POST, PUT, PATCH, DELETE
    action_roles = {"export": (PRINCIPAL, ADMIN)}      # per custom action
```

`RolePermission` runs before the view and checks that the user:
1. is authenticated and active,
2. belongs to a school and has a role,
3. has a role in the list for this action/method.

Otherwise the response is `403`.

### 2. School isolation (`SchoolScopedMixin`)

Every query is filtered by `school_id = request.user.school_id`. A record from another
school is invisible (`404`). Every foreign key in a request body is validated with
`SchoolScopedPrimaryKeyRelatedField`, so you cannot attach another school's class or
student by guessing an ID (`400`).

### 3. Row-level scope for teachers

In `get_queryset`, teachers are limited to:
* **classes**: classes where they are the form teacher, or have an assignment in the current session (`teacher_classroom_ids`);
* **students and guardians**: those in such classes;
* **score sheets**: sheets where `teacher = me`;
* **class results and summaries**: their form class only.

A teacher asking for another class's student gets `404`, not `403`, so the API does not reveal that the record exists.

### 4. Object rules inside actions

Some rules depend on the record, not just the role. These live in services:
* Only the sheet's own teacher can save or submit scores.
* Only the form teacher can write `class_teacher_comment`; only the principal can write `principal_comment`.
* Admins cannot change or deactivate the principal, change their own role, or create principal accounts.

### 5. Audit

Create, update and delete through the standard viewsets are logged automatically with
before/after values. Workflow actions (submit, approve, publish, unlock, payments,
reversals, imports, login) are logged explicitly. See `apps/audit`.

## Adding a new endpoint safely

1. Subclass `SchoolModelViewSet` (or `SchoolReadOnlyViewSet`) so school scoping and auditing come for free.
2. Set `read_roles`, `write_roles` and `action_roles`. **Don't leave writes open by accident**: `write_roles` defaults to `()` (nobody).
3. If teachers can read it, filter the queryset for `TEACHER` in `get_queryset`.
4. Use `SchoolPK` (`apps.core.fields`) for every foreign key in serializers.
5. Add a row to `READ_MATRIX` in `apps/core/tests/test_permissions.py`.
