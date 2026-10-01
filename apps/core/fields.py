from rest_framework import serializers


class SchoolScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """A primary-key field that only accepts objects from the requesting user's school.

    Prevents a user in school A from attaching records from school B by guessing IDs.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.context.get("request")
        school_id = getattr(getattr(request, "user", None), "school_id", None)
        if not school_id:
            return queryset.none()
        return queryset.filter(school_id=school_id)


SchoolPK = SchoolScopedPrimaryKeyRelatedField
