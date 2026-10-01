import io

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.attendance.models import AttendanceRecord
from apps.audit.models import AuditLog
from apps.core.testing import SchoolAPITestCase
from apps.students.importer import detect_mapping, parse_class, split_full_name
from apps.students.models import Guardian, Student


class StudentCrudTests(SchoolAPITestCase):
    def test_admin_creates_student_with_guardians_and_is_audited(self):
        guardian = Guardian.objects.create(school=self.w.school, first_name="Mrs", last_name="Ade", phone="08000009999")
        response = self.as_user(self.w.admin).post("/api/v1/students/", {
            "admission_number": "ADM/900", "first_name": "Ada", "last_name": "Ade", "gender": "female",
            "classroom": self.w.jss1a.id, "guardian_ids": [guardian.id],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["guardians"][0]["phone"], "08000009999")
        self.assertTrue(AuditLog.objects.filter(action="student.created", object_id=str(response.data["id"])).exists())

    def test_duplicate_admission_number_rejected(self):
        response = self.as_user(self.w.admin).post("/api/v1/students/", {
            "admission_number": "adm/001", "first_name": "X", "last_name": "Y",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("admission_number", response.data)

    def test_update_is_audited_with_changes(self):
        student = self.w.students_a[0]
        self.as_user(self.w.admin).patch(f"/api/v1/students/{student.id}/", {"first_name": "Renamed"}, format="json")
        log = AuditLog.objects.get(action="student.updated", object_id=str(student.id))
        self.assertEqual(log.changes["first_name"]["to"], "Renamed")

    def test_cannot_delete_student_with_history(self):
        student = self.w.students_a[0]
        AttendanceRecord.objects.create(school=self.w.school, student=student, classroom=self.w.jss1a,
                                        term=self.w.term, date=self.w.term.start_date)
        response = self.as_user(self.w.admin).delete(f"/api/v1/students/{student.id}/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "protected")

    def test_filters_and_search(self):
        client = self.as_user(self.w.principal)
        self.assertEqual(client.get(f"/api/v1/students/?classroom={self.w.jss1b.id}").data["count"], 3)
        self.assertEqual(client.get("/api/v1/students/?search=Kid2").data["count"], 1)

    def test_export_csv(self):
        response = self.as_user(self.w.principal).get("/api/v1/students/export/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        content = response.content.decode()
        self.assertIn("Admission number", content)
        self.assertIn("ADM/001", content)
        self.assertEqual(self.as_user(self.w.bursar).get("/api/v1/students/export/").status_code, 403)

    def test_class_students_action(self):
        response = self.as_user(self.w.teacher_a).get(f"/api/v1/classes/{self.w.jss1a.id}/students/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)


class ImporterUnitTests(SchoolAPITestCase):
    def test_header_detection(self):
        mapping = detect_mapping(["S/N", "Surname", "First Name", "Adm. No", "Class", "Parent's Phone", "Sex"])
        self.assertEqual(mapping["last_name"], "Surname")
        self.assertEqual(mapping["admission_number"], "Adm. No")
        self.assertEqual(mapping["guardian_phone"], "Parent's Phone")
        self.assertEqual(mapping["gender"], "Sex")

    def test_class_parsing(self):
        self.assertEqual(parse_class("JSS 1A"), ("JSS1", "A"))
        self.assertEqual(parse_class("jss1-b"), ("JSS1", "B"))
        self.assertEqual(parse_class("SSS 2 Gold"), ("SS2", "GOLD"))
        self.assertIsNone(parse_class("Primary 4"))

    def test_full_name_split(self):
        self.assertEqual(split_full_name("OKAFOR Chinedu Emeka"), ("Chinedu", "Emeka", "OKAFOR"))
        self.assertEqual(split_full_name("Okafor, Chinedu"), ("Chinedu", "", "Okafor"))


class StudentImportTests(SchoolAPITestCase):
    CSV = (
        "Admission No,Surname,First Name,Class,Sex,Date of Birth,Parent Name,Parent Phone\n"
        "IMP/001,okafor,chinedu,JSS 1A,M,12/03/2013,Mrs Ngozi Okafor,8031234567\n"
        "IMP/002,Bello,Amina,jss1b,F,2013-05-01,Mr Bello,08039876543\n"
        "IMP/003,Eze,Ada,JSS 3C,F,,,\n"
        "ADM/001,Duplicate,Kid,JSS 1A,F,,,\n"
        ",NoAdm,Kid,JSS 1A,X,31/02/2013,,\n"
    )

    def upload(self, content, name="students.csv", **extra):
        client = self.as_user(self.w.admin)
        return client.post("/api/v1/students/imports/preview/",
                           {"file": SimpleUploadedFile(name, content), **extra}, format="multipart")

    def test_preview_reports_errors_and_commit_creates_valid_rows(self):
        response = self.upload(self.CSV.encode())
        self.assertEqual(response.status_code, 201, response.data)
        report = response.data
        self.assertEqual(report["total_rows"], 5)
        self.assertEqual(report["valid_rows"], 2)
        self.assertEqual(report["error_count"], 3)
        messages = " ".join(m for e in report["errors"] for m in e["errors"])
        self.assertIn("does not exist yet", messages)
        self.assertIn("already exists", messages)
        self.assertIn("Admission number is missing", messages)
        self.assertFalse(Student.objects.filter(admission_number="IMP/001").exists())

        commit = self.as_user(self.w.admin).post(f"/api/v1/students/imports/{report['import_id']}/commit/")
        self.assertEqual(commit.status_code, 200, commit.data)
        self.assertEqual(commit.data["created_count"], 2)
        student = Student.objects.get(admission_number="IMP/001")
        self.assertEqual(student.last_name, "Okafor")  # title-cased
        self.assertEqual(student.classroom, self.w.jss1a)
        guardian = student.guardians.get()
        self.assertEqual(guardian.phone, "08031234567")  # leading zero restored
        self.assertEqual(guardian.first_name, "Mrs Ngozi")

        again = self.as_user(self.w.admin).post(f"/api/v1/students/imports/{report['import_id']}/commit/")
        self.assertEqual(again.status_code, 409)

    def test_xlsx_import(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Student register 2026"])  # title row above the header is skipped
        ws.append(["Reg No", "Full Name", "Class Arm", "Gender"])
        ws.append(["X/1", "ADEYEMI Tolu", "JSS1A", "F"])
        ws.append(["X/2", "Musa Ibrahim", "JSS 1B", "M"])
        buffer = io.BytesIO()
        wb.save(buffer)
        response = self.upload(buffer.getvalue(), name="register.xlsx")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["valid_rows"], 2)
        self.as_user(self.w.admin).post(f"/api/v1/students/imports/{response.data['import_id']}/commit/")
        self.assertEqual(Student.objects.get(admission_number="X/1").first_name, "Tolu")

    def test_missing_required_columns(self):
        response = self.upload(b"Name,Phone\nA B,0800\n")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "failed")
        self.assertIn("admission_number", response.data["missing_required_columns"])

    def test_rejects_other_file_types_and_non_admins(self):
        self.assertEqual(self.upload(b"hello", name="notes.txt").status_code, 400)
        client = self.as_user(self.w.principal)
        response = client.post("/api/v1/students/imports/preview/",
                               {"file": SimpleUploadedFile("s.csv", self.CSV.encode())}, format="multipart")
        self.assertEqual(response.status_code, 403)

    def test_manual_column_mapping_override(self):
        content = b"Code,Last,First,Group\nM/1,Obi,Kene,JSS 1A\n"
        response = self.upload(content, column_mapping='{"Code": "admission_number", "Last": "last_name", '
                                                      '"First": "first_name", "Group": "classroom"}')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["valid_rows"], 1)
