"""Role-based access control.

How it works
------------
Every API view declares which roles may use it:

    class StudentViewSet(SchoolModelViewSet):
        read_roles = (PRINCIPAL, ADMIN, BURSAR, TEACHER)
        write_roles = (ADMIN,)
        action_roles = {"export": (PRINCIPAL, ADMIN)}

`RolePermission` checks the logged-in user's role against that declaration on
every request. Row-level limits (for example "a teacher only sees students in
their own classes") are applied in each view's `get_queryset`, so records a
user may not see simply do not exist for them (404, not 403).
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .roles import ALL_ROLES


def is_school_staff(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and getattr(user, "school_id", None)
        and getattr(user, "role", "")
    )


class IsSchoolStaff(BasePermission):
    """Authenticated, active user who belongs to a school and has a role."""

    message = "Your account is not linked to a school role."

    def has_permission(self, request, view):
        return is_school_staff(request.user)


class RolePermission(IsSchoolStaff):
    """Allow the request only if the user's role is in the view's required roles."""

    message = "Your role does not have access to this resource."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        get_roles = getattr(view, "get_required_roles", None)
        roles = get_roles() if callable(get_roles) else ALL_ROLES
        return request.user.role in roles


class RoleAccessMixin:
    """Declarative role configuration for views (see module docstring)."""

    permission_classes = [RolePermission]
    read_roles: tuple = ALL_ROLES
    write_roles: tuple = ()
    action_roles: dict = {}

    def get_required_roles(self):
        action = getattr(self, "action", None)
        if action and action in self.action_roles:
            return self.action_roles[action]
        if self.request.method in SAFE_METHODS:
            return self.read_roles
        return self.write_roles

    # Convenience helpers for views and serializers
    @property
    def user_role(self) -> str:
        return getattr(self.request.user, "role", "")

    def has_role(self, *roles) -> bool:
        return self.user_role in roles
