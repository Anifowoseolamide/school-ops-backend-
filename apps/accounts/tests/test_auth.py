from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.testing import PASSWORD, SchoolAPITestCase

User = get_user_model()


class LoginTests(SchoolAPITestCase):
    def login(self, email, password=PASSWORD):
        return APIClient().post("/api/v1/auth/login/", {"email": email, "password": password}, format="json")

    def test_login_returns_tokens_profile_and_capabilities(self):
        response = self.login("PRINCIPAL@test.test")  # email is case-insensitive
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["role"], "principal")
        self.assertIn("audit.view", response.data["user"]["capabilities"])
        self.assertTrue(AuditLog.objects.filter(action="auth.login", actor=self.w.principal).exists())

    def test_wrong_password_is_rejected_and_audited(self):
        response = self.login("principal@test.test", "wrong-password")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action="auth.login_failed").exists())

    def test_inactive_user_cannot_log_in(self):
        self.w.teacher_b.is_active = False
        self.w.teacher_b.save()
        self.assertEqual(self.login("teacher.b@test.test").status_code, 401)

    def test_platform_superuser_cannot_use_school_api(self):
        User.objects.create_superuser(email="root@test.test", password=PASSWORD, first_name="Root", last_name="User")
        response = self.login("root@test.test")
        self.assertEqual(response.status_code, 400)

    def test_access_token_works_and_logout_blacklists_refresh(self):
        tokens = self.login("bursar@test.test").data
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(client.get("/api/v1/auth/me/").data["email"], "bursar@test.test")
        self.assertEqual(client.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}, format="json").status_code, 205)
        refreshed = APIClient().post("/api/v1/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(refreshed.status_code, 401)

    def test_unauthenticated_requests_are_rejected(self):
        self.assertEqual(APIClient().get("/api/v1/students/").status_code, 401)


class ProfileAndPasswordTests(SchoolAPITestCase):
    def test_me_update_cannot_change_role(self):
        client = self.as_user(self.w.teacher_a)
        response = client.patch("/api/v1/auth/me/", {"phone": "08000001111", "role": "principal"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.w.teacher_a.refresh_from_db()
        self.assertEqual(self.w.teacher_a.phone, "08000001111")
        self.assertEqual(self.w.teacher_a.role, "teacher")

    def test_change_password(self):
        client = self.as_user(self.w.teacher_a)
        bad = client.post("/api/v1/auth/change-password/", {"current_password": "nope", "new_password": "N3w-Secret-Pass"})
        self.assertEqual(bad.status_code, 400)
        ok = client.post("/api/v1/auth/change-password/", {"current_password": PASSWORD, "new_password": "N3w-Secret-Pass"})
        self.assertEqual(ok.status_code, 200)
        self.w.teacher_a.refresh_from_db()
        self.assertTrue(self.w.teacher_a.check_password("N3w-Secret-Pass"))

    def test_password_reset_flow(self):
        client = APIClient()
        unknown = client.post("/api/v1/auth/password-reset/", {"email": "nobody@test.test"})
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        client.post("/api/v1/auth/password-reset/", {"email": "admin@test.test"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("reset-password?uid=", mail.outbox[0].body)

        uid = urlsafe_base64_encode(force_bytes(self.w.admin.pk))
        token = default_token_generator.make_token(self.w.admin)
        response = client.post("/api/v1/auth/password-reset/confirm/",
                               {"uid": uid, "token": token, "new_password": "Brand-New-Pass-9"})
        self.assertEqual(response.status_code, 200)
        reused = client.post("/api/v1/auth/password-reset/confirm/",
                             {"uid": uid, "token": token, "new_password": "Another-Pass-77"})
        self.assertEqual(reused.status_code, 400)


class StaffManagementTests(SchoolAPITestCase):
    def test_admin_creates_staff_with_temporary_password(self):
        client = self.as_user(self.w.admin)
        response = client.post("/api/v1/staff/", {
            "email": "new.teacher@test.test", "first_name": "New", "last_name": "Teacher", "role": "teacher",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["temporary_password"])
        user = User.objects.get(email="new.teacher@test.test")
        self.assertEqual(user.school, self.w.school)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(response.data["temporary_password"]))
        # The temporary password is only shown once
        self.assertIsNone(client.get(f"/api/v1/staff/{user.id}/").data["temporary_password"])

    def test_admin_cannot_create_principal_or_change_own_role(self):
        client = self.as_user(self.w.admin)
        response = client.post("/api/v1/staff/", {
            "email": "p2@test.test", "first_name": "P", "last_name": "Two", "role": "principal",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        response = client.patch(f"/api/v1/staff/{self.w.admin.id}/", {"role": "bursar"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_admin_cannot_touch_principal_account(self):
        client = self.as_user(self.w.admin)
        self.assertEqual(client.post(f"/api/v1/staff/{self.w.principal.id}/deactivate/").status_code, 403)
        self.assertEqual(client.patch(f"/api/v1/staff/{self.w.principal.id}/", {"phone": "1"}, format="json").status_code, 400)

    def test_principal_can_view_but_not_create(self):
        client = self.as_user(self.w.principal)
        self.assertEqual(client.get("/api/v1/staff/").status_code, 200)
        response = client.post("/api/v1/staff/", {"email": "x@test.test", "first_name": "X", "last_name": "Y",
                                                  "role": "teacher"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_teacher_and_bursar_cannot_list_staff(self):
        self.assertEqual(self.as_user(self.w.teacher_a).get("/api/v1/staff/").status_code, 403)
        self.assertEqual(self.as_user(self.w.bursar).get("/api/v1/staff/").status_code, 403)

    def test_deactivate_and_reset_password(self):
        client = self.as_user(self.w.admin)
        response = client.post(f"/api/v1/staff/{self.w.teacher_b.id}/deactivate/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        response = client.post(f"/api/v1/staff/{self.w.teacher_b.id}/reset-password/")
        self.assertEqual(response.status_code, 200)
        self.w.teacher_b.refresh_from_db()
        self.assertTrue(self.w.teacher_b.check_password(response.data["temporary_password"]))
        self.assertTrue(self.w.teacher_b.must_change_password)

    def test_staff_cannot_be_deleted(self):
        self.assertEqual(self.as_user(self.w.admin).delete(f"/api/v1/staff/{self.w.teacher_b.id}/").status_code, 405)
