"""Test helpers shared by every app's tests.

`SchoolWorld` builds a small but complete school:
  * principal, admin, bursar, two teachers (teacher_a is form teacher of JSS 1A
    and teaches Mathematics + English there; teacher_b teaches JSS 1B)
  * current session and term
  * classes JSS 1A and JSS 1B with 3 students each
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.core.roles import ADMIN, BURSAR, PRINCIPAL, TEACHER
from apps.schools.models import AcademicSession, ClassRoom, Subject, TeacherAssignment, Term
from apps.schools.services import create_school, set_current_term
from apps.students.models import Guardian, Student

User = get_user_model()
PASSWORD = "Str0ng-Pass-123"


class SchoolWorld:
    def __init__(self, name="Test School", email_prefix=""):
        p = email_prefix
        self.school = create_school(name)
        today = timezone.localdate()
        self.session = AcademicSession.objects.create(
            school=self.school, name=f"{today.year}/{today.year + 1}",
            start_date=today - timedelta(days=60), end_date=today + timedelta(days=300),
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name="first",
            start_date=today - timedelta(days=30), end_date=today + timedelta(days=60),
        )
        set_current_term(self.term)

        def user(email, role, first, last="Tester"):
            return User.objects.create_user(email=f"{p}{email}", password=PASSWORD, first_name=first, last_name=last,
                                            school=self.school, role=role)

        self.principal = user("principal@test.test", PRINCIPAL, "Pat")
        self.admin = user("admin@test.test", ADMIN, "Ade")
        self.bursar = user("bursar@test.test", BURSAR, "Bola")
        self.teacher_a = user("teacher.a@test.test", TEACHER, "Tola")
        self.teacher_b = user("teacher.b@test.test", TEACHER, "Tobi")

        self.jss1a = ClassRoom.objects.create(school=self.school, level="JSS1", arm="A", class_teacher=self.teacher_a)
        self.jss1b = ClassRoom.objects.create(school=self.school, level="JSS1", arm="B", class_teacher=self.teacher_b)
        self.maths = Subject.objects.create(school=self.school, name="Mathematics")
        self.english = Subject.objects.create(school=self.school, name="English Language")
        for classroom, teacher in ((self.jss1a, self.teacher_a), (self.jss1b, self.teacher_b)):
            for subject in (self.maths, self.english):
                TeacherAssignment.objects.create(school=self.school, session=self.session, classroom=classroom,
                                                 subject=subject, teacher=teacher)
        self.students_a = [self._student(self.jss1a, i) for i in range(1, 4)]
        self.students_b = [self._student(self.jss1b, i) for i in range(4, 7)]

    def _student(self, classroom, n):
        guardian = Guardian.objects.create(school=self.school, first_name="Parent", last_name=f"No{n}",
                                           phone=f"0800000{n:04d}", email=f"parent{n}@example.com")
        student = Student.objects.create(school=self.school, admission_number=f"ADM/{n:03d}", first_name=f"Kid{n}",
                                         last_name=f"Family{n}", gender="female" if n % 2 else "male",
                                         classroom=classroom)
        student.guardians.add(guardian)
        return student

    def user_for(self, role):
        return {PRINCIPAL: self.principal, ADMIN: self.admin, BURSAR: self.bursar, TEACHER: self.teacher_a}[role]


class SchoolAPITestCase(APITestCase):
    """APITestCase with a SchoolWorld and helpers to act as a role."""

    @classmethod
    def setUpTestData(cls):
        cls.w = SchoolWorld()

    def as_user(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def as_role(self, role) -> APIClient:
        return self.as_user(self.w.user_for(role))
