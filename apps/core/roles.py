"""The staff roles used across the platform.

Kept in `core` (not `accounts`) so every app can import it without circular imports.
"""
from django.db import models


class Role(models.TextChoices):
    PRINCIPAL = "principal", "Principal / Proprietor"
    ADMIN = "admin", "School Admin"
    BURSAR = "bursar", "Bursar"
    TEACHER = "teacher", "Teacher"


PRINCIPAL = Role.PRINCIPAL
ADMIN = Role.ADMIN
BURSAR = Role.BURSAR
TEACHER = Role.TEACHER

ALL_ROLES = (PRINCIPAL, ADMIN, BURSAR, TEACHER)
MANAGEMENT = (PRINCIPAL, ADMIN)
FINANCE_READ = (PRINCIPAL, BURSAR)
NO_ROLES: tuple = ()

# Returned to the frontend at login and on /auth/me so it can decide which
# menus and screens to show. The server still enforces every rule itself.
ROLE_CAPABILITIES = {
    PRINCIPAL: [
        "dashboard.principal",
        "school.manage",
        "staff.view",
        "classes.view",
        "students.view",
        "guardians.view",
        "attendance.view",
        "fees.view",
        "payments.view",
        "results.view",
        "results.approve",
        "results.publish",
        "results.unlock",
        "results.comment_principal",
        "report_cards.view",
        "audit.view",
    ],
    ADMIN: [
        "dashboard.admin",
        "school.manage",
        "staff.manage",
        "classes.manage",
        "assignments.manage",
        "students.manage",
        "students.import",
        "guardians.manage",
        "attendance.view",
        "results.view",
        "results.review",
        "report_cards.generate",
    ],
    BURSAR: [
        "dashboard.bursar",
        "classes.view",
        "students.view_basic",
        "guardians.view",
        "fees.manage",
        "payments.record",
        "payments.reverse",
    ],
    TEACHER: [
        "dashboard.teacher",
        "classes.view_own",
        "students.view_own",
        "guardians.view_own",
        "attendance.mark_own",
        "results.enter_own",
        "results.comment_class_teacher",
    ],
}
