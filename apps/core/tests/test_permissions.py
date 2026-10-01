"""The role matrix from the product plan, checked endpoint by endpoint.

Each row: (url, {role: expected GET status}). 200 = allowed, 403 = role not allowed.
"""
from apps.core.roles import ADMIN, BURSAR, PRINCIPAL, TEACHER
from apps.core.testing import SchoolAPITestCase, SchoolWorld
from apps.students.models import Student

ALLOW, DENY = 200, 403

READ_MATRIX = [
    ("/api/v1/students/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: ALLOW, TEACHER: ALLOW}),
    ("/api/v1/guardians/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: ALLOW, TEACHER: ALLOW}),
    ("/api/v1/staff/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: DENY, TEACHER: DENY}),
    ("/api/v1/classes/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: ALLOW, TEACHER: ALLOW}),
    ("/api/v1/assignments/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: DENY, TEACHER: ALLOW}),
    ("/api/v1/fees/structures/", {PRINCIPAL: ALLOW, ADMIN: DENY, BURSAR: ALLOW, TEACHER: DENY}),
    ("/api/v1/fees/invoices/", {PRINCIPAL: ALLOW, ADMIN: DENY, BURSAR: ALLOW, TEACHER: DENY}),
    ("/api/v1/fees/payments/", {PRINCIPAL: ALLOW, ADMIN: DENY, BURSAR: ALLOW, TEACHER: DENY}),
    ("/api/v1/fees/reports/outstanding/", {PRINCIPAL: ALLOW, ADMIN: DENY, BURSAR: ALLOW, TEACHER: DENY}),
    ("/api/v1/results/sheets/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: DENY, TEACHER: ALLOW}),
    ("/api/v1/results/class-results/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: DENY, TEACHER: ALLOW}),
    ("/api/v1/results/missing/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: DENY, TEACHER: DENY}),
    ("/api/v1/attendance/records/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: DENY, TEACHER: ALLOW}),
    ("/api/v1/attendance/summary/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: DENY, TEACHER: ALLOW}),
    ("/api/v1/audit/logs/", {PRINCIPAL: ALLOW, ADMIN: DENY, BURSAR: DENY, TEACHER: DENY}),
    ("/api/v1/students/imports/", {PRINCIPAL: DENY, ADMIN: ALLOW, BURSAR: DENY, TEACHER: DENY}),
    ("/api/v1/dashboards/principal/", {PRINCIPAL: ALLOW, ADMIN: DENY, BURSAR: DENY, TEACHER: DENY}),
    ("/api/v1/dashboards/admin/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: DENY, TEACHER: DENY}),
    ("/api/v1/dashboards/bursar/", {PRINCIPAL: ALLOW, ADMIN: DENY, BURSAR: ALLOW, TEACHER: DENY}),
    ("/api/v1/dashboards/teacher/", {PRINCIPAL: DENY, ADMIN: DENY, BURSAR: DENY, TEACHER: ALLOW}),
    ("/api/v1/school/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: ALLOW, TEACHER: ALLOW}),
    ("/api/v1/terms/", {PRINCIPAL: ALLOW, ADMIN: ALLOW, BURSAR: ALLOW, TEACHER: ALLOW}),
]


class RoleMatrixTests(SchoolAPITestCase):
    def test_read_access_matches_role_matrix(self):
        for url, expectations in READ_MATRIX:
            for role, expected in expectations.items():
                with self.subTest(url=url, role=role):
                    response = self.as_role(role).get(url)
                    self.assertEqual(response.status_code, expected, f"{role} GET {url}: {response.data}")

    def test_write_access_on_students(self):
        payload = {"admission_number": "NEW/1", "first_name": "New", "last_name": "Kid", "classroom": self.w.jss1a.id}
        for role, expected in ((PRINCIPAL, 403), (BURSAR, 403), (TEACHER, 403), (ADMIN, 201)):
            with self.subTest(role=role):
                self.assertEqual(self.as_role(role).post("/api/v1/students/", payload, format="json").status_code, expected)

    def test_write_access_on_school_setup(self):
        for role, expected in ((TEACHER, 403), (BURSAR, 403), (ADMIN, 201)):
            with self.subTest(role=role):
                response = self.as_role(role).post("/api/v1/subjects/", {"name": f"Subject {role}"}, format="json")
                self.assertEqual(response.status_code, expected)
        self.assertEqual(self.as_role(PRINCIPAL).patch("/api/v1/school/", {"motto": "Hello"}, format="json").status_code, 200)
        self.assertEqual(self.as_role(TEACHER).patch("/api/v1/school/", {"motto": "Hello"}, format="json").status_code, 403)


class TeacherScopeTests(SchoolAPITestCase):
    def test_teacher_sees_only_own_classes_and_students(self):
        client = self.as_user(self.w.teacher_a)
        classes = client.get("/api/v1/classes/").data["results"]
        self.assertEqual([c["id"] for c in classes], [self.w.jss1a.id])
        students = client.get("/api/v1/students/").data
        self.assertEqual(students["count"], 3)
        other = self.w.students_b[0]
        self.assertEqual(client.get(f"/api/v1/students/{other.id}/").status_code, 404)

    def test_teacher_sees_only_guardians_of_own_students(self):
        client = self.as_user(self.w.teacher_a)
        self.assertEqual(client.get("/api/v1/guardians/").data["count"], 3)

    def test_bursar_gets_basic_student_fields_only(self):
        data = self.as_user(self.w.bursar).get(f"/api/v1/students/{self.w.students_a[0].id}/").data
        self.assertIn("guardians", data)
        self.assertNotIn("date_of_birth", data)
        self.assertNotIn("address", data)


class SchoolIsolationTests(SchoolAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other = SchoolWorld(name="Other School", email_prefix="other.")

    def test_users_never_see_another_schools_data(self):
        client = self.as_user(self.other.principal)
        self.assertEqual(client.get("/api/v1/students/").data["count"], 3 + 3)
        self.assertEqual(client.get(f"/api/v1/students/{self.w.students_a[0].id}/").status_code, 404)
        ids = {s["id"] for s in client.get("/api/v1/students/?page_size=100").data["results"]}
        self.assertFalse(ids & {s.id for s in self.w.students_a})

    def test_cannot_attach_records_from_another_school(self):
        client = self.as_user(self.other.admin)
        response = client.post("/api/v1/students/", {
            "admission_number": "X/1", "first_name": "A", "last_name": "B", "classroom": self.w.jss1a.id,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("classroom", response.data)
        self.assertFalse(Student.objects.filter(admission_number="X/1").exists())
