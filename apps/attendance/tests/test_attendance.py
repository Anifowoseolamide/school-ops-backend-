from datetime import timedelta

from django.utils import timezone

from apps.attendance.models import AttendanceRecord
from apps.core.testing import SchoolAPITestCase


class RegisterTests(SchoolAPITestCase):
    def test_get_register_defaults_to_present(self):
        response = self.as_user(self.w.teacher_a).get("/api/v1/attendance/register/", {"classroom": self.w.jss1a.id})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_marked"])
        self.assertEqual({s["status"] for s in response.data["students"]}, {"present"})

    def test_teacher_marks_own_class_and_others_default_to_present(self):
        absent = self.w.students_a[0]
        response = self.as_user(self.w.teacher_a).post("/api/v1/attendance/register/", {
            "classroom": self.w.jss1a.id,
            "records": [{"student": absent.id, "status": "absent", "note": "Sick"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["is_marked"])
        today = timezone.localdate()
        self.assertEqual(AttendanceRecord.objects.filter(classroom=self.w.jss1a, date=today).count(), 3)
        self.assertEqual(AttendanceRecord.objects.get(student=absent, date=today).status, "absent")

        # Saving again updates instead of duplicating
        self.as_user(self.w.teacher_a).post("/api/v1/attendance/register/", {"classroom": self.w.jss1a.id}, format="json")
        self.assertEqual(AttendanceRecord.objects.filter(classroom=self.w.jss1a, date=today).count(), 3)
        self.assertEqual(AttendanceRecord.objects.get(student=absent, date=today).status, "present")

    def test_teacher_cannot_mark_another_class(self):
        response = self.as_user(self.w.teacher_a).post("/api/v1/attendance/register/", {"classroom": self.w.jss1b.id},
                                                       format="json")
        self.assertEqual(response.status_code, 404)

    def test_student_must_belong_to_class(self):
        response = self.as_user(self.w.teacher_a).post("/api/v1/attendance/register/", {
            "classroom": self.w.jss1a.id, "records": [{"student": self.w.students_b[0].id, "status": "absent"}],
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_future_dates_and_dates_outside_terms_are_rejected(self):
        client = self.as_user(self.w.teacher_a)
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.assertEqual(client.post("/api/v1/attendance/register/", {"classroom": self.w.jss1a.id, "date": tomorrow},
                                     format="json").status_code, 400)
        before_term = (self.w.term.start_date - timedelta(days=5)).isoformat()
        self.assertEqual(client.post("/api/v1/attendance/register/", {"classroom": self.w.jss1a.id, "date": before_term},
                                     format="json").status_code, 400)

    def test_principal_and_admin_view_but_cannot_mark(self):
        for user in (self.w.principal, self.w.admin):
            client = self.as_user(user)
            self.assertEqual(client.get("/api/v1/attendance/register/", {"classroom": self.w.jss1a.id}).status_code, 200)
            self.assertEqual(client.post("/api/v1/attendance/register/", {"classroom": self.w.jss1a.id},
                                         format="json").status_code, 403)

    def test_daily_summary_and_student_summary(self):
        self.as_user(self.w.teacher_a).post("/api/v1/attendance/register/", {
            "classroom": self.w.jss1a.id, "records": [{"student": self.w.students_a[0].id, "status": "absent"}],
        }, format="json")
        summary = self.as_user(self.w.principal).get("/api/v1/attendance/summary/").data
        self.assertEqual(summary["totals"]["classes_marked"], 1)
        self.assertEqual(summary["totals"]["classes_total"], 2)
        self.assertEqual(summary["totals"]["absent"], 1)
        student = self.as_user(self.w.principal).get(f"/api/v1/attendance/students/{self.w.students_a[0].id}/summary/").data
        self.assertEqual(student["days"], 1)
        self.assertEqual(student["absent"], 1)
