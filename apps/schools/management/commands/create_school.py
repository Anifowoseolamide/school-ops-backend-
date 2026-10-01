from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.roles import PRINCIPAL
from apps.schools.services import create_school


class Command(BaseCommand):
    help = "Create a new school with its principal account (platform operator command)."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="School name")
        parser.add_argument("--principal-email", required=True)
        parser.add_argument("--principal-first-name", default="School")
        parser.add_argument("--principal-last-name", default="Principal")
        parser.add_argument("--principal-password", required=True)
        parser.add_argument("--phone", default="")
        parser.add_argument("--address", default="")

    @transaction.atomic
    def handle(self, *args, **opts):
        User = get_user_model()
        email = opts["principal_email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f"A user with email {email} already exists.")
        school = create_school(opts["name"], phone=opts["phone"], address=opts["address"])
        User.objects.create_user(
            email=email,
            password=opts["principal_password"],
            first_name=opts["principal_first_name"],
            last_name=opts["principal_last_name"],
            school=school,
            role=PRINCIPAL,
        )
        self.stdout.write(self.style.SUCCESS(f"Created school '{school.name}' (id={school.id}) with principal {email}."))
