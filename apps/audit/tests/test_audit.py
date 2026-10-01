from apps.audit.models import AuditLog
from apps.audit.services import record_audit
from apps.core.testing import SchoolAPITestCase


class AuditLogTests(SchoolAPITestCase):
    def test_entries_are_append_only(self):
        log = record_audit(None, "test.action", self.w.school, actor=self.w.principal)
        log.action = "changed"
        with self.assertRaises(PermissionError):
            log.save()
        with self.assertRaises(PermissionError):
            log.delete()
        with self.assertRaises(PermissionError):
            AuditLog.objects.filter(pk=log.pk).update(action="x")
        with self.assertRaises(PermissionError):
            AuditLog.objects.all().delete()

    def test_principal_can_search_log(self):
        self.as_user(self.w.admin).post("/api/v1/subjects/", {"name": "French"}, format="json")
        response = self.as_user(self.w.principal).get("/api/v1/audit/logs/?action=subject")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        entry = response.data["results"][0]
        self.assertEqual(entry["action"], "subject.created")
        self.assertEqual(entry["actor_email"], "admin@test.test")
        self.assertEqual(entry["actor_role"], "admin")

    def test_logs_are_scoped_to_school(self):
        from apps.core.testing import SchoolWorld

        other = SchoolWorld(name="Elsewhere", email_prefix="x.")
        record_audit(None, "secret.thing", other.school, actor=other.principal)
        response = self.as_user(self.w.principal).get("/api/v1/audit/logs/?action=secret")
        self.assertEqual(response.data["count"], 0)
