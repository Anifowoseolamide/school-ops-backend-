from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "actor",
            "actor_name",
            "actor_email",
            "actor_role",
            "action",
            "object_type",
            "object_id",
            "object_repr",
            "changes",
            "metadata",
            "ip_address",
            "user_agent",
        ]
        read_only_fields = fields

    def get_actor_name(self, obj) -> str:
        return obj.actor.full_name if obj.actor_id and obj.actor else (obj.actor_email or "System")
