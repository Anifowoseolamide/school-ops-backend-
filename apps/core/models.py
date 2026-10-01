from django.db import models, transaction


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SchoolOwnedModel(TimeStampedModel):
    """Base class for every record that belongs to one school (tenant).

    Every query in the API is filtered by `school`, so a second school is just
    more rows, never a schema change.
    """

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="+",
        db_index=True,
    )

    class Meta:
        abstract = True


class Sequence(models.Model):
    """Per-school counters for human-readable numbers (invoices, receipts)."""

    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="sequences")
    key = models.CharField(max_length=50)
    value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["school", "key"], name="uniq_sequence_school_key")]

    def __str__(self):
        return f"{self.school_id}:{self.key}={self.value}"


def next_sequence_value(school, key: str) -> int:
    """Atomically increment and return the next number for `key` in `school`."""
    with transaction.atomic():
        seq, _ = Sequence.objects.select_for_update().get_or_create(school=school, key=key)
        seq.value = models.F("value") + 1
        seq.save(update_fields=["value"])
        seq.refresh_from_db(fields=["value"])
        return seq.value
