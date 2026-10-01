from django.core.management import call_command

from apps.core.testing import SchoolAPITestCase
from apps.fees import services as fee_services
from apps.fees.models import FeeItem, FeeStructure
from apps.results import services as result_services


class DashboardTests(SchoolAPITestCase):
    def setUp(self):
        structure = FeeStructure.objects.create(school=self.w.school, term=self.w.term, level="JSS1")
        FeeItem.objects.create(structure=structure, name="Tuition", amount_kobo=100_000_00)
        fee_services.generate_invoices_for_structure(structure, self.w.bursar)
        result_services.setup_term(self.w.term)

    def test_principal_dashboard(self):
        data = self.as_user(self.w.principal).get("/api/v1/dashboards/principal/").data
        self.assertEqual(data["counts"]["students"], 6)
        self.assertEqual(data["fees"]["totals"]["billed_kobo"], 6 * 100_000_00)
        types = {item["type"] for item in data["needs_attention"]}
        self.assertIn("scores_missing", types)
        self.assertIn("students_owing", types)
        self.assertEqual(len(data["staff_activity"]), 5)

    def test_bursar_dashboard(self):
        data = self.as_user(self.w.bursar).get("/api/v1/dashboards/bursar/").data
        self.assertEqual(len(data["top_debtors"]), 6)
        self.assertEqual(data["today"]["count"], 0)

    def test_admin_dashboard(self):
        data = self.as_user(self.w.admin).get("/api/v1/dashboards/admin/").data
        self.assertEqual(data["counts"]["students"], 6)
        self.assertEqual(data["results"]["sheets_total"], 4)

    def test_teacher_dashboard(self):
        data = self.as_user(self.w.teacher_a).get("/api/v1/dashboards/teacher/").data
        self.assertEqual([c["name"] for c in data["form_classes"]], ["JSS 1A"])
        self.assertEqual(len(data["score_sheets"]), 2)
        self.assertEqual(data["sheets_to_finish"], 2)


class SeedCommandTests(SchoolAPITestCase):
    def test_seed_demo_runs(self):
        call_command("seed_demo", students_per_class=3, verbosity=0, stdout=open("/dev/null", "w"))
        from apps.schools.models import School

        school = School.objects.get(slug="sample-secondary-school")
        self.assertEqual(school.staff.count(), 23)
