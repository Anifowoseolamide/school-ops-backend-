from decimal import Decimal

from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.testing import SchoolAPITestCase
from apps.fees import services as fee_services
from apps.fees.models import FeeItem, FeeStructure
from apps.results import services
from apps.results.models import ClassResult, ResultSummary, ScoreSheet
from apps.results.services import competition_rank


class RankingUnitTests(SchoolAPITestCase):
    def test_competition_ranking_handles_ties(self):
        ranks = competition_rank([(1, Decimal("80")), (2, Decimal("75")), (3, Decimal("75")), (4, Decimal("60"))])
        self.assertEqual(ranks, {1: 1, 2: 2, 3: 2, 4: 4})


class ResultsTestCase(SchoolAPITestCase):
    def setUp(self):
        services.setup_term(self.w.term)
        self.sheet_maths = ScoreSheet.objects.get(classroom=self.w.jss1a, subject=self.w.maths)
        self.sheet_english = ScoreSheet.objects.get(classroom=self.w.jss1a, subject=self.w.english)
        self.class_result = ClassResult.objects.get(classroom=self.w.jss1a, term=self.w.term)

    def teacher(self):
        return self.as_user(self.w.teacher_a)

    def fill(self, sheet, scores):
        """scores: list of (ca1, ca2, exam) in the order of students_a."""
        rows = [{"student": s.id, "ca1": a, "ca2": b, "exam": c} for s, (a, b, c) in zip(self.w.students_a, scores)]
        return self.teacher().put(f"/api/v1/results/sheets/{sheet.id}/scores/", {"scores": rows}, format="json")

    def submit_all(self):
        self.fill(self.sheet_maths, [(18, 17, 50), (15, 15, 40), (10, 10, 30)])
        self.fill(self.sheet_english, [(16, 16, 48), (17, 18, 45), (10, 10, 30)])
        for sheet in (self.sheet_maths, self.sheet_english):
            self.assertEqual(self.teacher().post(f"/api/v1/results/sheets/{sheet.id}/submit/").status_code, 200)


class SetupTests(ResultsTestCase):
    def test_setup_creates_sheets_from_assignments_and_is_idempotent(self):
        self.assertEqual(ScoreSheet.objects.filter(term=self.w.term).count(), 4)
        response = self.as_user(self.w.admin).post("/api/v1/results/setup/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["sheets_created"], 0)
        self.assertEqual(self.as_user(self.w.teacher_a).post("/api/v1/results/setup/", {}).status_code, 403)

    def test_teacher_sees_only_own_sheets(self):
        sheets = self.teacher().get("/api/v1/results/sheets/").data["results"]
        self.assertEqual({s["id"] for s in sheets}, {self.sheet_maths.id, self.sheet_english.id})
        other = ScoreSheet.objects.get(classroom=self.w.jss1b, subject=self.w.maths)
        self.assertEqual(self.teacher().get(f"/api/v1/results/sheets/{other.id}/").status_code, 404)


class ScoreEntryTests(ResultsTestCase):
    def test_save_scores_computes_total_and_grade(self):
        response = self.fill(self.sheet_maths, [(18, 17, 50), (15, 15, 40), (10, 10, 15)])
        self.assertEqual(response.status_code, 200, response.data)
        rows = {r["student"]: r for r in response.data["rows"]}
        first = rows[self.w.students_a[0].id]
        self.assertEqual(Decimal(first["total"]), Decimal("85"))
        self.assertEqual(first["grade"], "A1")
        self.assertEqual(rows[self.w.students_a[2].id]["grade"], "F9")
        self.assertEqual(response.data["progress"]["missing"], 0)

    def test_partial_entry_has_no_total(self):
        response = self.teacher().patch(f"/api/v1/results/sheets/{self.sheet_maths.id}/scores/", {
            "scores": [{"student": self.w.students_a[0].id, "ca1": 12}]}, format="json")
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data["rows"] if r["student"] == self.w.students_a[0].id)
        self.assertIsNone(row["total"])

    def test_scores_above_maximum_rejected(self):
        response = self.fill(self.sheet_maths, [(25, 10, 50), (10, 10, 61), (10, 10, 10)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("scores", response.data)

    def test_student_from_other_class_rejected(self):
        response = self.teacher().put(f"/api/v1/results/sheets/{self.sheet_maths.id}/scores/", {
            "scores": [{"student": self.w.students_b[0].id, "ca1": 10}]}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_only_the_subject_teacher_can_enter_scores(self):
        sheet_b = ScoreSheet.objects.get(classroom=self.w.jss1b, subject=self.w.maths)
        response = self.teacher().put(f"/api/v1/results/sheets/{sheet_b.id}/scores/",
                                      {"scores": [{"student": self.w.students_b[0].id, "ca1": 1}]}, format="json")
        self.assertEqual(response.status_code, 404)
        admin = self.as_user(self.w.admin).put(f"/api/v1/results/sheets/{self.sheet_maths.id}/scores/",
                                               {"scores": [{"student": self.w.students_a[0].id, "ca1": 1}]}, format="json")
        self.assertEqual(admin.status_code, 403)

    def test_submit_requires_complete_sheet_and_locks_it(self):
        self.fill(self.sheet_maths, [(18, 17, 50), (15, 15, None), (10, 10, 30)])
        self.assertEqual(self.teacher().post(f"/api/v1/results/sheets/{self.sheet_maths.id}/submit/").status_code, 400)
        self.fill(self.sheet_maths, [(18, 17, 50), (15, 15, 40), (10, 10, 30)])
        self.assertEqual(self.teacher().post(f"/api/v1/results/sheets/{self.sheet_maths.id}/submit/").status_code, 200)
        self.assertEqual(self.fill(self.sheet_maths, [(1, 1, 1)] * 3).status_code, 409)

    def test_admin_returns_sheet_with_note(self):
        self.submit_all()
        response = self.as_user(self.w.admin).post(f"/api/v1/results/sheets/{self.sheet_maths.id}/return/",
                                                   {"note": "Check student 3"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "returned")
        self.assertEqual(self.fill(self.sheet_maths, [(18, 17, 50), (15, 15, 40), (12, 10, 30)]).status_code, 200)


class WorkflowTests(ResultsTestCase):
    def test_full_workflow_to_publish(self):
        admin, principal = self.as_user(self.w.admin), self.as_user(self.w.principal)
        url = f"/api/v1/results/class-results/{self.class_result.id}"
        self.assertEqual(admin.post(f"{url}/begin-review/").status_code, 400)  # sheets not submitted
        self.submit_all()
        response = admin.post(f"{url}/begin-review/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "in_review")

        self.assertEqual(admin.post(f"{url}/approve/").status_code, 403)  # only principal approves
        self.assertEqual(principal.post(f"{url}/publish/").status_code, 409)  # must approve first
        self.assertEqual(principal.post(f"{url}/approve/").data["status"], "approved")
        self.assertEqual(principal.post(f"{url}/publish/").data["status"], "published")

        summaries = principal.get(f"{url}/summaries/").data
        by_student = {s["student"]: s for s in summaries}
        first = by_student[self.w.students_a[0].id]
        self.assertEqual(Decimal(first["total"]), Decimal("165"))   # 85 + 80
        self.assertEqual(Decimal(first["average"]), Decimal("82.50"))
        self.assertEqual(first["position"], 1)
        self.assertEqual(by_student[self.w.students_a[2].id]["position"], 3)
        self.assertEqual(first["class_size"], 3)
        self.assertTrue(AuditLog.objects.filter(action="results.published").exists())

    def test_returning_a_sheet_reopens_review(self):
        self.submit_all()
        services.begin_review(self.class_result, self.w.admin)
        self.as_user(self.w.admin).post(f"/api/v1/results/sheets/{self.sheet_maths.id}/return/", {"note": "fix"}, format="json")
        self.class_result.refresh_from_db()
        self.assertEqual(self.class_result.status, "open")

    def test_unlock_requires_reason_and_is_audited(self):
        self.submit_all()
        for step in (services.begin_review, services.approve, services.publish):
            step(self.class_result, self.w.principal)
        url = f"/api/v1/results/class-results/{self.class_result.id}/unlock/"
        principal = self.as_user(self.w.principal)
        self.assertEqual(principal.post(url, {}, format="json").status_code, 400)
        response = principal.post(url, {"reason": "Wrong exam score for student 2"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "in_review")
        log = AuditLog.objects.get(action="results.unlocked")
        self.assertEqual(log.metadata["reason"], "Wrong exam score for student 2")

    def test_missing_scores_tracker(self):
        self.fill(self.sheet_maths, [(18, 17, 50), (15, 15, None), (10, 10, 30)])
        data = self.as_user(self.w.principal).get("/api/v1/results/missing/").data
        self.assertEqual(data["sheets_total"], 4)
        self.assertEqual(data["sheets_pending"], 4)
        maths = next(p for p in data["pending"] if p["sheet"] == self.sheet_maths.id)
        self.assertEqual(maths["missing"], 1)


class CommentsAndReportCardTests(ResultsTestCase):
    def setUp(self):
        super().setUp()
        self.submit_all()
        services.begin_review(self.class_result, self.w.admin)
        self.summary = ResultSummary.objects.get(class_result=self.class_result, student=self.w.students_a[0])

    def test_comment_permissions(self):
        url = f"/api/v1/results/summaries/{self.summary.id}/"
        teacher = self.as_user(self.w.teacher_a)
        self.assertEqual(teacher.patch(url, {"class_teacher_comment": "Great work"}, format="json").status_code, 200)
        self.assertEqual(teacher.patch(url, {"principal_comment": "Hi"}, format="json").status_code, 403)
        principal = self.as_user(self.w.principal)
        self.assertEqual(principal.patch(url, {"principal_comment": "Excellent"}, format="json").status_code, 200)
        self.assertEqual(principal.patch(url, {"class_teacher_comment": "x"}, format="json").status_code, 403)
        other_teacher = self.as_user(self.w.teacher_b)
        self.assertEqual(other_teacher.patch(url, {"class_teacher_comment": "x"}, format="json").status_code, 404)
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.class_teacher_comment, "Great work")

    def test_draft_report_card_pdf_for_staff(self):
        response = self.as_user(self.w.admin).get(f"/api/v1/results/class-results/{self.class_result.id}/report-cards/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        single = self.as_user(self.w.teacher_a).get(f"/api/v1/results/summaries/{self.summary.id}/report-card/")
        self.assertEqual(single.status_code, 200)

    def test_share_link_only_after_publish_and_hold_for_debtors(self):
        principal = self.as_user(self.w.principal)
        link_url = f"/api/v1/results/summaries/{self.summary.id}/share-link/"
        self.assertEqual(principal.get(link_url).status_code, 409)
        services.approve(self.class_result, self.w.principal)
        services.publish(self.class_result, self.w.principal)
        url = principal.get(link_url).data["url"].split("localhost:8000")[1]
        self.assertEqual(APIClient().get(url).status_code, 200)

        structure = FeeStructure.objects.create(school=self.w.school, term=self.w.term, level="JSS1")
        FeeItem.objects.create(structure=structure, name="Tuition", amount_kobo=1000)
        fee_services.generate_invoices_for_structure(structure)
        settings_obj = self.w.school.settings
        settings_obj.hold_report_cards_for_debtors = True
        settings_obj.save()
        self.assertEqual(APIClient().get(url).status_code, 403)

    def test_bursar_has_no_access_to_results(self):
        self.assertEqual(self.as_user(self.w.bursar).get(f"/api/v1/results/summaries/{self.summary.id}/").status_code, 403)
