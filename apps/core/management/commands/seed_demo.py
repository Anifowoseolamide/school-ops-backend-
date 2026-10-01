"""Create a realistic demo school.

    python manage.py seed_demo            # adds the demo school (fails if it exists)
    python manage.py seed_demo --reset    # wipes the whole database first (DEBUG only)

All people, phone numbers and emails are fictional. Emails use the reserved
`.test` and `example.com` domains; phone numbers use an unassigned 0800000 range.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.attendance.models import AttendanceRecord, AttendanceStatus
from apps.audit.services import record_audit
from apps.core.roles import ADMIN, BURSAR, PRINCIPAL, TEACHER
from apps.fees import services as fee_services
from apps.fees.models import AdjustmentKind, FeeItem, FeeStructure, Payment, PaymentMethod, PaymentStatus
from apps.results import services as result_services
from apps.results.models import ClassResult, ResultSummary, Score, ScoreSheet, SheetStatus
from apps.schools.models import AcademicSession, ClassLevel, ClassRoom, Subject, TeacherAssignment, Term, TermName
from apps.schools.services import create_school, grade_for, set_current_term
from apps.students.models import Gender, Guardian, Student

User = get_user_model()

DEMO_SLUG = "sample-secondary-school"
DEMO_PASSWORD = "DemoPass123!"
EMAIL_DOMAIN = "sample-school.test"

MALE_FIRST = ["Chinedu", "Tunde", "Emeka", "Ibrahim", "Segun", "Obinna", "Kunle", "Musa", "Uche", "Femi", "Ifeanyi",
              "Yusuf", "Chukwuemeka", "Babatunde", "Abdullahi", "Kelechi", "Damilola", "Tobi", "Sani", "Nnamdi",
              "Olumide", "Ikenna", "Gbenga", "Aliyu", "Chidi", "Ayodeji", "Ebuka", "Bayo", "Umar", "Somto"]
FEMALE_FIRST = ["Ngozi", "Amina", "Funmilayo", "Chiamaka", "Aisha", "Adaeze", "Bisola", "Zainab", "Ifeoma", "Yetunde",
                "Halima", "Chioma", "Temitope", "Fatima", "Nneka", "Folake", "Hauwa", "Ebere", "Kemi", "Blessing",
                "Oluwaseun", "Amarachi", "Rukayat", "Ogechi", "Titilayo", "Khadija", "Uchenna", "Toyin", "Maryam", "Ada"]
SURNAMES = ["Okafor", "Adeyemi", "Bello", "Eze", "Okonkwo", "Ibrahim", "Ogunleye", "Nwosu", "Abubakar", "Adebayo",
            "Okeke", "Mohammed", "Balogun", "Chukwu", "Danjuma", "Olawale", "Nwachukwu", "Suleiman", "Ajayi", "Obi",
            "Afolabi", "Umeh", "Lawal", "Onyekachi", "Akinola", "Yakubu", "Emenike", "Oyelaran", "Garba", "Iwu",
            "Fashola", "Anyanwu", "Salami", "Ekwueme", "Bakare", "Okoro", "Usman", "Ogbonna", "Adeleke", "Musa"]

JSS_SUBJECTS = ["English Language", "Mathematics", "Basic Science", "Social Studies", "Civic Education",
                "Computer Studies", "Agricultural Science", "Business Studies"]
SS_SUBJECTS = ["English Language", "Mathematics", "Biology", "Chemistry", "Physics", "Economics",
               "Civic Education", "Computer Studies"]

JSS_FEES = [("Tuition", 150_000), ("Development levy", 15_000), ("Books and materials", 20_000), ("PTA levy", 5_000)]
SS_FEES = [("Tuition", 180_000), ("Laboratory fee", 15_000), ("Development levy", 15_000),
           ("Books and materials", 25_000), ("PTA levy", 5_000)]

CLASS_TEACHER_COMMENTS = {
    "high": ["An excellent term. Keep up the hard work.", "Outstanding performance and good conduct.",
             "A brilliant and focused student. Well done."],
    "mid": ["A good result. More effort in weaker subjects will help.", "Steady progress this term. Keep it up.",
            "Good conduct and fair performance. Aim higher next term."],
    "low": ["Needs to put in more effort and attend extra lessons.", "Can do better with more concentration in class.",
            "More dedication to studies is required next term."],
}
PRINCIPAL_COMMENTS = {
    "high": "Excellent result. Keep it up.",
    "mid": "A good result. Work harder next term.",
    "low": "Below expectation. The school will support you to improve.",
}


def naira(amount: int) -> int:
    return amount * 100


class Command(BaseCommand):
    help = "Create a demo school with ~300 students, staff, fees, payments, attendance and results."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Wipe ALL data first (only when DEBUG is true).")
        parser.add_argument("--students-per-class", type=int, default=25)
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, **opts):
        if opts["reset"]:
            if not settings.DEBUG:
                raise CommandError("--reset is only allowed when DJANGO_DEBUG is true.")
            self.stdout.write("Wiping the database...")
            call_command("flush", interactive=False, verbosity=0)
        from apps.schools.models import School

        if School.objects.filter(slug=DEMO_SLUG).exists():
            raise CommandError("The demo school already exists. Run with --reset to start again.")
        self.rng = random.Random(opts["seed"])
        with transaction.atomic():
            self._build(opts["students_per_class"])
        self._print_summary()

    # ------------------------------------------------------------------
    def log(self, message):
        self.stdout.write(f"  - {message}")

    def _build(self, per_class):
        rng = self.rng
        today = timezone.localdate()

        # School and calendar --------------------------------------------------
        self.school = school = create_school(
            "Sample Secondary School", slug=DEMO_SLUG, address="12 Example Road, Ikeja, Lagos",
            phone="0800 000 0000", email=f"info@{EMAIL_DOMAIN}", motto="Knowledge and Character",
        )
        school.settings.minimum_part_payment_kobo = naira(20_000)
        school.settings.report_card_footer = "This is a demo report card generated with fictional data."
        school.settings.save()

        term_start = today - timedelta(days=today.weekday()) - timedelta(weeks=5)
        term_end = term_start + timedelta(weeks=14) - timedelta(days=3)
        session = AcademicSession.objects.create(
            school=school, name=f"{term_start.year}/{term_start.year + 1}",
            start_date=term_start, end_date=term_start + timedelta(weeks=46),
        )
        self.term = Term.objects.create(school=school, session=session, name=TermName.FIRST,
                                        start_date=term_start, end_date=term_end)
        Term.objects.create(school=school, session=session, name=TermName.SECOND,
                            start_date=term_end + timedelta(weeks=3), end_date=term_end + timedelta(weeks=16))
        Term.objects.create(school=school, session=session, name=TermName.THIRD,
                            start_date=term_end + timedelta(weeks=18), end_date=session.end_date)
        set_current_term(self.term)
        self.log(f"School, session {session.name} and three terms (first term is current)")

        # Staff ----------------------------------------------------------------
        def staff(email, first, last, role, phone):
            user = User.objects.create_user(email=email, password=DEMO_PASSWORD, first_name=first, last_name=last,
                                            school=school, role=role, phone=phone)
            user.last_login = timezone.now() - timedelta(hours=rng.randint(1, 72))
            user.save(update_fields=["last_login"])
            return user

        self.principal = staff(f"principal@{EMAIL_DOMAIN}", "Folake", "Adeyemi", PRINCIPAL, "08000000001")
        self.admin = staff(f"admin@{EMAIL_DOMAIN}", "Emeka", "Obi", ADMIN, "08000000002")
        self.bursar = staff(f"bursar@{EMAIL_DOMAIN}", "Halima", "Yusuf", BURSAR, "08000000003")
        self.demo_teacher = staff(f"teacher@{EMAIL_DOMAIN}", "Ngozi", "Okafor", TEACHER, "08000000004")
        teachers = [self.demo_teacher]
        used = {("Ngozi", "Okafor")}
        while len(teachers) < 20:
            gender = rng.choice([Gender.MALE, Gender.FEMALE])
            first = rng.choice(MALE_FIRST if gender == Gender.MALE else FEMALE_FIRST)
            last = rng.choice(SURNAMES)
            if (first, last) in used:
                continue
            used.add((first, last))
            n = len(teachers) + 1
            teachers.append(staff(f"teacher{n}@{EMAIL_DOMAIN}", first, last, TEACHER, f"0800000{n + 10:04d}"))
        self.teachers = teachers
        self.log("Principal, admin, bursar and 20 teachers")

        # Classes and subjects ------------------------------------------------------
        self.classes = []
        form_teachers = teachers[1:12]
        for level in ClassLevel.values:
            for arm in ("A", "B"):
                self.classes.append(ClassRoom.objects.create(school=school, level=level, arm=arm, capacity=35))
        jss2a = next(c for c in self.classes if c.level == "JSS2" and c.arm == "A")
        jss2a.class_teacher = self.demo_teacher
        jss2a.save()
        others = [c for c in self.classes if c.pk != jss2a.pk]
        for classroom, teacher in zip(others, form_teachers):
            classroom.class_teacher = teacher
            classroom.save()

        subjects = {name: Subject.objects.create(school=school, name=name, code=name[:3].upper())
                    for name in dict.fromkeys(JSS_SUBJECTS + SS_SUBJECTS)}
        subject_teachers = {}
        pool = teachers[1:]
        for i, name in enumerate(subjects):
            subject_teachers[name] = [pool[i % len(pool)], pool[(i + 7) % len(pool)]]
        for classroom in self.classes:
            names = JSS_SUBJECTS if classroom.level.startswith("JSS") else SS_SUBJECTS
            for name in names:
                if name == "Mathematics" and classroom.level in ("JSS1", "JSS2"):
                    teacher = self.demo_teacher
                else:
                    candidates = subject_teachers[name]
                    teacher = candidates[0] if classroom.arm == "A" else candidates[1]
                TeacherAssignment.objects.create(school=school, session=session, classroom=classroom,
                                                 subject=subjects[name], teacher=teacher)
        self.log("12 classes (JSS 1A to SS 3B), 12 subjects, teacher assignments")

        # Students and guardians ----------------------------------------------------
        self.students = []
        guardian_counter = 0
        previous_guardian = None
        adm = 0
        for classroom in self.classes:
            entry_year = term_start.year - (ClassLevel.values.index(classroom.level))
            for _ in range(per_class):
                adm += 1
                gender = rng.choice([Gender.MALE, Gender.FEMALE])
                first = rng.choice(MALE_FIRST if gender == Gender.MALE else FEMALE_FIRST)
                middle = rng.choice(MALE_FIRST + FEMALE_FIRST) if rng.random() < 0.6 else ""
                if previous_guardian and rng.random() < 0.1:
                    guardian = previous_guardian
                    last = guardian.last_name
                else:
                    last = rng.choice(SURNAMES)
                    guardian_counter += 1
                    is_father = rng.random() < 0.55
                    guardian = Guardian.objects.create(
                        school=school,
                        first_name=("Mr " if is_father else "Mrs ") + rng.choice(MALE_FIRST if is_father else FEMALE_FIRST),
                        last_name=last,
                        relationship="Father" if is_father else "Mother",
                        phone=f"0800000{guardian_counter + 1000:04d}",
                        email=f"parent{guardian_counter}@example.com" if rng.random() < 0.7 else "",
                    )
                age = 10 + ClassLevel.values.index(classroom.level) + rng.randint(0, 1)
                student = Student.objects.create(
                    school=school,
                    admission_number=f"SSS/{entry_year}/{adm:04d}",
                    first_name=first, middle_name=middle, last_name=last, gender=gender,
                    date_of_birth=today - timedelta(days=age * 365 + rng.randint(0, 364)),
                    classroom=classroom,
                    admission_date=term_start.replace(year=entry_year),
                )
                student.guardians.add(guardian)
                student._ability = max(25, min(95, rng.gauss(62, 13)))
                self.students.append(student)
                previous_guardian = guardian
        self.log(f"{len(self.students)} students with {guardian_counter} guardians (some siblings share a guardian)")

        self._fees()
        self._attendance(today)
        self._results()
        for user in (self.principal, self.admin, self.bursar, self.demo_teacher):
            record_audit(None, "auth.login", user, actor=user)

    # ------------------------------------------------------------------
    def _fees(self):
        rng, school = self.rng, self.school
        for level in ClassLevel.values:
            items = JSS_FEES if level.startswith("JSS") else SS_FEES
            structure = FeeStructure.objects.create(
                school=school, term=self.term, level=level, name=f"{ClassLevel(level).label} fees",
                due_date=self.term.start_date + timedelta(weeks=3),
            )
            FeeItem.objects.bulk_create([FeeItem(structure=structure, name=n, amount_kobo=naira(a), position=i)
                                         for i, (n, a) in enumerate(items)])
            fee_services.generate_invoices_for_structure(structure, self.bursar)

        invoices = list(fee_services.Invoice.objects.filter(school=school, term=self.term).select_related("student"))
        rng.shuffle(invoices)
        for invoice in invoices[:3]:
            fee_services.add_adjustment(invoice, kind=AdjustmentKind.SCHOLARSHIP, amount_kobo=invoice.total_kobo // 2,
                                        reason="Academic scholarship (50%)", user=self.bursar)
        now = timezone.now()
        span = max((timezone.localdate() - self.term.start_date).days, 1)
        paid = part = 0
        for index, invoice in enumerate(invoices):
            invoice.refresh_from_db()
            roll = index / len(invoices)
            if roll < 0.60:
                amounts = [invoice.balance_kobo] if rng.random() < 0.7 else [
                    invoice.balance_kobo // 2, invoice.balance_kobo - invoice.balance_kobo // 2]
                paid += 1
            elif roll < 0.85:
                fraction = rng.uniform(0.35, 0.8)
                amounts = [int(invoice.balance_kobo * fraction) // 100_000 * 100_000 or naira(20_000)]
                part += 1
            else:
                continue
            for amount in amounts:
                when = now - timedelta(days=rng.randint(0, span), hours=rng.randint(0, 8))
                method = rng.choices(
                    [PaymentMethod.BANK_TRANSFER, PaymentMethod.PAYSTACK, PaymentMethod.CASH, PaymentMethod.POS],
                    weights=[45, 30, 15, 10],
                )[0]
                if method == PaymentMethod.PAYSTACK:
                    payment = Payment.objects.create(
                        school=school, invoice=invoice, student=invoice.student, amount_kobo=amount,
                        method=method, status=PaymentStatus.SUCCESSFUL,
                        reference=fee_services.new_payment_reference("PSK"), external_reference=f"demo-{invoice.id}",
                        channel=rng.choice(["card", "bank_transfer", "ussd"]), paid_at=when,
                        payer_email=f"parent{invoice.student_id}@example.com",
                    )
                    fee_services._issue_receipt(payment)
                else:
                    fee_services.record_manual_payment(
                        invoice, amount_kobo=amount, method=method, user=self.bursar, paid_at=when,
                        external_reference=f"TRF{rng.randint(10**8, 10**9 - 1)}" if method == PaymentMethod.BANK_TRANSFER else "",
                        payer_name=invoice.student.guardians.first().full_name,
                    )
                invoice.refresh_from_db()
        self.log(f"Fee structures, {len(invoices)} invoices: {paid} paid, {part} part-paid, "
                 f"{len(invoices) - paid - part} owing; 3 scholarships")

    def _attendance(self, today):
        rng, school = self.rng, self.school
        days = []
        day = self.term.start_date
        while day <= today and day <= self.term.end_date:
            if day.weekday() < 5:
                days.append(day)
            day += timedelta(days=1)
        days = days[-20:]
        unmarked_today = {c.pk for c in self.classes if (c.level, c.arm) in {("JSS2", "A"), ("SS1", "B"), ("SS3", "A")}}
        records = []
        by_class = {}
        for s in self.students:
            by_class.setdefault(s.classroom_id, []).append(s)
        for day in days:
            for classroom in self.classes:
                if day == today and classroom.pk in unmarked_today:
                    continue
                marker = classroom.class_teacher or self.demo_teacher
                for s in by_class.get(classroom.pk, []):
                    r = rng.random()
                    status = (AttendanceStatus.PRESENT if r < 0.93 else AttendanceStatus.LATE if r < 0.96
                              else AttendanceStatus.ABSENT if r < 0.99 else AttendanceStatus.EXCUSED)
                    records.append(AttendanceRecord(school=school, student=s, classroom=classroom, term=self.term,
                                                    date=day, status=status, marked_by=marker))
        AttendanceRecord.objects.bulk_create(records, batch_size=2000)
        self.log(f"{len(records)} attendance records over {len(days)} school days "
                 f"(3 classes left unmarked today)")

    def _results(self):
        rng, school = self.rng, self.school
        result_services.setup_term(self.term)
        bands = result_services.get_bands(school)
        ability = {s.id: s._ability for s in self.students}
        name_of = {c.pk: c.name for c in self.classes}

        def cls(level, arm):
            return next(c for c in self.classes if c.level == level and c.arm == arm)

        published, approved = cls("JSS1", "A"), cls("JSS1", "B")
        in_review = [cls("SS1", "A"), cls("SS2", "A")]
        incomplete = cls("JSS3", "A")
        demo_draft = cls("JSS2", "A")
        returned_class = cls("SS3", "B")

        scores = []
        sheets = list(ScoreSheet.objects.filter(school=school, term=self.term).select_related("subject", "classroom"))
        by_class = {}
        for s in self.students:
            by_class.setdefault(s.classroom_id, []).append(s)
        for sheet in sheets:
            difficulty = rng.uniform(-6, 6)
            students = by_class.get(sheet.classroom_id, [])
            partial = sheet.classroom_id == demo_draft.pk and sheet.teacher_id == self.demo_teacher.pk
            incomplete_sheet = sheet.classroom_id == incomplete.pk and sheet.subject.name in ("English Language", "Mathematics")
            for i, student in enumerate(students):
                level = max(5, min(98, ability[student.id] + difficulty + rng.gauss(0, 7))) / 100
                ca1 = Decimal(min(20, max(0, round(level * 20 + rng.uniform(-2, 2)))))
                ca2 = Decimal(min(20, max(0, round(level * 20 + rng.uniform(-2, 2)))))
                exam = Decimal(min(60, max(0, round(level * 60 + rng.uniform(-5, 5)))))
                if partial and i >= 10:
                    ca2, exam = None, None
                if incomplete_sheet and i % 4 == 0:
                    exam = None
                score = Score(sheet=sheet, student=student, ca1=ca1, ca2=ca2, exam=exam, entered_by=sheet.teacher)
                if score.is_complete:
                    score.total = ca1 + ca2 + exam
                    score.grade, score.remark = grade_for(score.total, bands)
                scores.append(score)
        Score.objects.bulk_create(scores, batch_size=2000)

        now = timezone.now()
        for sheet in sheets:
            if sheet.classroom_id == demo_draft.pk and sheet.teacher_id == self.demo_teacher.pk:
                continue  # left in draft for the live demo
            if sheet.classroom_id == incomplete.pk and sheet.subject.name in ("English Language", "Mathematics"):
                continue  # missing scores -> shows in "needs attention"
            if sheet.classroom_id not in (published.pk, approved.pk, *[c.pk for c in in_review]) and rng.random() < 0.12:
                continue  # some complete sheets not yet submitted
            sheet.status = SheetStatus.SUBMITTED
            sheet.submitted_at = now - timedelta(days=rng.randint(0, 5))
            sheet.submitted_by = sheet.teacher
            sheet.save()
        returned = ScoreSheet.objects.filter(classroom=returned_class, term=self.term, subject__name="Physics").first()
        if returned:
            returned.status = SheetStatus.RETURNED
            returned.returned_by = self.admin
            returned.returned_at = now - timedelta(days=1)
            returned.return_note = "Three exam scores look higher than the marked scripts. Please check and resubmit."
            returned.save()

        def finish(classroom, stop):
            cr = ClassResult.objects.get(term=self.term, classroom=classroom)
            cr.sheets.update(status=SheetStatus.SUBMITTED, submitted_at=now)
            cr = result_services.begin_review(cr, self.admin)
            if stop == "in_review":
                return cr
            cr = result_services.approve(cr, self.principal)
            if stop == "approved":
                return cr
            for summary in ResultSummary.objects.filter(class_result=cr):
                band = "high" if summary.average >= 70 else "mid" if summary.average >= 50 else "low"
                summary.class_teacher_comment = rng.choice(CLASS_TEACHER_COMMENTS[band])
                summary.principal_comment = PRINCIPAL_COMMENTS[band]
                summary.save()
            cr.next_term_begins = self.term.end_date + timedelta(weeks=3)
            cr.save()
            return result_services.publish(cr, self.principal)

        finish(published, "published")
        finish(approved, "approved")
        for c in in_review:
            finish(c, "in_review")
        self.log(f"Results: {name_of[published.pk]} published, {name_of[approved.pk]} approved, "
                 f"{', '.join(name_of[c.pk] for c in in_review)} in review, "
                 f"{name_of[incomplete.pk]} missing scores, {name_of[demo_draft.pk]} Maths in draft, "
                 f"{name_of[returned_class.pk]} Physics returned")

    def _print_summary(self):
        self.stdout.write(self.style.SUCCESS("\nDemo school created."))
        self.stdout.write(f"All demo accounts use the password: {DEMO_PASSWORD}\n")
        for role, email in [
            ("Principal", f"principal@{EMAIL_DOMAIN}"),
            ("Admin", f"admin@{EMAIL_DOMAIN}"),
            ("Bursar", f"bursar@{EMAIL_DOMAIN}"),
            ("Teacher (form teacher of JSS 2A, teaches JSS1-2 Maths)", f"teacher@{EMAIL_DOMAIN}"),
            ("Other teachers", f"teacher2@{EMAIL_DOMAIN} ... teacher20@{EMAIL_DOMAIN}"),
        ]:
            self.stdout.write(f"  {role:<55} {email}")
