import hashlib
import hmac
import json
from unittest import mock

from django.test import override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.core.testing import SchoolAPITestCase
from apps.fees import services
from apps.fees.models import FeeItem, FeeStructure, Invoice, Payment, Receipt
from apps.notifications.models import NotificationLog

SECRET = "sk_test_secret"


def naira(n):
    return n * 100


class FeesTestCase(SchoolAPITestCase):
    def setUp(self):
        self.structure = FeeStructure.objects.create(school=self.w.school, term=self.w.term, level="JSS1")
        FeeItem.objects.create(structure=self.structure, name="Tuition", amount_kobo=naira(100_000))
        FeeItem.objects.create(structure=self.structure, name="Books", amount_kobo=naira(20_000))
        services.generate_invoices_for_structure(self.structure, self.w.bursar)
        self.student = self.w.students_a[0]
        self.invoice = Invoice.objects.get(student=self.student, term=self.w.term)

    def bursar(self):
        return self.as_user(self.w.bursar)


class FeeStructureTests(FeesTestCase):
    def test_bursar_creates_structure_with_items(self):
        from apps.schools.models import Term

        term2 = Term.objects.create(school=self.w.school, session=self.w.session, name="second",
                                    start_date=self.w.term.end_date.replace(day=1), end_date=self.w.session.end_date)
        response = self.bursar().post("/api/v1/fees/structures/", {
            "term": term2.id, "level": "JSS1", "items": [
                {"name": "Tuition", "amount_kobo": naira(90_000)}, {"name": "PTA", "amount_kobo": naira(5_000)}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["total_kobo"], naira(95_000))
        duplicate = self.bursar().post("/api/v1/fees/structures/", {
            "term": term2.id, "level": "JSS1", "items": [{"name": "X", "amount_kobo": 100}]}, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_generate_invoices_is_idempotent(self):
        self.assertEqual(Invoice.objects.filter(term=self.w.term).count(), 6)
        response = self.bursar().post(f"/api/v1/fees/structures/{self.structure.id}/generate-invoices/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"created": 0, "skipped_existing": 6, "students_at_level": 6})
        self.assertEqual(self.invoice.total_kobo, naira(120_000))
        self.assertEqual(self.invoice.status, "unpaid")
        self.assertTrue(self.invoice.number.startswith("INV-"))

    def test_cannot_delete_structure_with_invoices(self):
        self.assertEqual(self.bursar().delete(f"/api/v1/fees/structures/{self.structure.id}/").status_code, 409)


class ManualPaymentTests(FeesTestCase):
    def pay(self, amount, **extra):
        return self.bursar().post("/api/v1/fees/payments/", {
            "invoice": self.invoice.id, "amount_kobo": amount, "method": "bank_transfer", **extra}, format="json")

    def test_part_then_full_payment_updates_status_and_receipts(self):
        response = self.pay(naira(50_000), external_reference="TRF001")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["receipt_number"].startswith("RCT-"))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "part_paid")
        self.assertEqual(self.invoice.balance_kobo, naira(70_000))
        receipt = Receipt.objects.get(payment_id=response.data["id"])
        self.assertEqual(receipt.balance_after_kobo, naira(70_000))

        self.assertEqual(self.pay(naira(70_000)).status_code, 201)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")
        self.assertEqual(self.invoice.balance_kobo, 0)
        self.assertEqual(self.pay(naira(1)).status_code, 409)  # already paid
        self.assertTrue(AuditLog.objects.filter(action="payment.recorded").count() >= 2)

    def test_overpayment_and_duplicate_reference_rejected(self):
        self.assertEqual(self.pay(naira(200_000)).status_code, 400)
        self.assertEqual(self.pay(naira(10_000), external_reference="TRF777").status_code, 201)
        self.assertEqual(self.pay(naira(10_000), external_reference="trf777").status_code, 409)

    def test_online_method_cannot_be_recorded_by_hand(self):
        response = self.bursar().post("/api/v1/fees/payments/", {
            "invoice": self.invoice.id, "amount_kobo": 100, "method": "paystack"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_reverse_payment(self):
        payment_id = self.pay(naira(30_000)).data["id"]
        response = self.bursar().post(f"/api/v1/fees/payments/{payment_id}/reverse/", {"reason": "Entered twice"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["amount_kobo"], -naira(30_000))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance_kobo, naira(120_000))
        self.assertEqual(self.invoice.status, "unpaid")
        again = self.bursar().post(f"/api/v1/fees/payments/{payment_id}/reverse/", {"reason": "again"}, format="json")
        self.assertEqual(again.status_code, 409)

    def test_payments_cannot_be_edited_or_deleted(self):
        payment_id = self.pay(naira(1_000)).data["id"]
        self.assertEqual(self.bursar().patch(f"/api/v1/fees/payments/{payment_id}/", {"amount_kobo": 1}).status_code, 405)
        self.assertEqual(self.bursar().delete(f"/api/v1/fees/payments/{payment_id}/").status_code, 405)

    def test_receipt_pdf_and_public_link(self):
        payment_id = self.pay(naira(5_000)).data["id"]
        pdf = self.bursar().get(f"/api/v1/fees/payments/{payment_id}/receipt/")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        url = self.bursar().get(f"/api/v1/fees/payments/{payment_id}/receipt-link/").data["url"]
        public = APIClient().get(url.split("localhost:8000")[1])
        self.assertEqual(public.status_code, 200)
        self.assertTrue(public.content.startswith(b"%PDF"))
        self.assertEqual(APIClient().get("/api/v1/public/receipts/forged-token/").status_code, 404)

    def test_principal_reads_but_cannot_record(self):
        client = self.as_user(self.w.principal)
        self.assertEqual(client.get("/api/v1/fees/invoices/").status_code, 200)
        response = client.post("/api/v1/fees/payments/", {
            "invoice": self.invoice.id, "amount_kobo": 100, "method": "cash"}, format="json")
        self.assertEqual(response.status_code, 403)


class InvoiceActionTests(FeesTestCase):
    def test_discount_reduces_total(self):
        response = self.bursar().post(f"/api/v1/fees/invoices/{self.invoice.id}/adjustments/", {
            "kind": "scholarship", "amount_kobo": naira(60_000), "reason": "50% scholarship"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["total_kobo"], naira(60_000))
        too_big = self.bursar().post(f"/api/v1/fees/invoices/{self.invoice.id}/adjustments/", {
            "kind": "discount", "amount_kobo": naira(70_000), "reason": "x"}, format="json")
        self.assertEqual(too_big.status_code, 400)

    def test_cancel_requires_no_payments(self):
        services.record_manual_payment(self.invoice, amount_kobo=naira(1_000), method="cash", user=self.w.bursar)
        self.assertEqual(self.bursar().post(f"/api/v1/fees/invoices/{self.invoice.id}/cancel/",
                                            {"reason": "Left school"}).status_code, 409)
        other = Invoice.objects.get(student=self.w.students_a[1])
        response = self.bursar().post(f"/api/v1/fees/invoices/{other.id}/cancel/", {"reason": "Left school"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")

    def test_one_off_invoice_and_duplicate_guard(self):
        response = self.bursar().post("/api/v1/fees/invoices/", {
            "student": self.student.id, "term": self.w.term.id, "lines": [{"description": "Excursion", "amount_kobo": 500}],
        }, format="json")
        self.assertEqual(response.status_code, 409)

    def test_filters(self):
        services.record_manual_payment(self.invoice, amount_kobo=naira(1_000), method="cash", user=self.w.bursar)
        client = self.bursar()
        self.assertEqual(client.get("/api/v1/fees/invoices/?status=part_paid").data["count"], 1)
        self.assertEqual(client.get(f"/api/v1/fees/invoices/?classroom={self.w.jss1b.id}").data["count"], 3)
        self.assertEqual(client.get("/api/v1/fees/invoices/?has_balance=true").data["count"], 6)

    def test_send_pay_link_notifies_guardians(self):
        response = self.bursar().post(f"/api/v1/fees/invoices/{self.invoice.id}/send-pay-link/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["messages_sent"], 2)  # email + sms
        self.assertEqual(NotificationLog.objects.filter(purpose="pay_link").count(), 2)

    def test_reports(self):
        services.record_manual_payment(self.invoice, amount_kobo=naira(20_000), method="cash", user=self.w.bursar)
        report = self.bursar().get("/api/v1/fees/reports/outstanding/").data
        self.assertEqual(report["totals"]["billed_kobo"], naira(720_000))
        self.assertEqual(report["totals"]["collected_kobo"], naira(20_000))
        self.assertEqual(len(report["classes"]), 2)
        collections = self.bursar().get("/api/v1/fees/reports/collections/").data
        self.assertEqual(collections["total_kobo"], naira(20_000))
        self.assertEqual(collections["by_method"]["cash"]["count"], 1)


def paystack_response(data, status=True, code=200):
    response = mock.Mock()
    response.status_code = code
    response.json.return_value = {"status": status, "message": "ok", "data": data}
    return response


@override_settings(PAYSTACK_SECRET_KEY=SECRET, PAYSTACK_PUBLIC_KEY="pk_test_x")
class OnlinePaymentTests(FeesTestCase):
    def token(self):
        return self.bursar().get(f"/api/v1/fees/invoices/{self.invoice.id}/pay-link/").data["url"].rsplit("/", 1)[-1]

    def start(self, amount=None):
        body = {"email": "parent@example.com"}
        if amount:
            body["amount_kobo"] = amount
        with mock.patch("apps.fees.paystack.requests.request") as req:
            req.return_value = paystack_response({"authorization_url": "https://checkout.paystack.com/abc",
                                                  "access_code": "abc"})
            response = APIClient().post(f"/api/v1/public/pay/{self.token()}/initialize/", body, format="json")
        return response, req

    def webhook(self, payload, secret=SECRET):
        raw = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
        return APIClient().post("/api/v1/payments/paystack/webhook/", raw, content_type="application/json",
                                HTTP_X_PAYSTACK_SIGNATURE=signature)

    def test_public_invoice_view(self):
        response = APIClient().get(f"/api/v1/public/pay/{self.token()}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["balance_kobo"], naira(120_000))
        self.assertEqual(response.data["student"]["name"], self.student.full_name)
        self.assertTrue(response.data["online_payments_available"])

    def test_start_payment_creates_pending_payment(self):
        response, req = self.start()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["authorization_url"], "https://checkout.paystack.com/abc")
        sent = req.call_args.kwargs["json"]
        self.assertEqual(sent["amount"], naira(120_000))
        self.assertEqual(sent["currency"], "NGN")
        payment = Payment.objects.get(reference=response.data["reference"])
        self.assertEqual(payment.status, "pending")

    def test_part_payment_rules(self):
        settings_obj = self.w.school.settings
        settings_obj.minimum_part_payment_kobo = naira(50_000)
        settings_obj.save()
        self.assertEqual(self.start(naira(10_000))[0].status_code, 400)
        self.assertEqual(self.start(naira(60_000))[0].status_code, 201)
        settings_obj.allow_part_payment = False
        settings_obj.save()
        self.assertEqual(self.start(naira(60_000))[0].status_code, 400)

    def test_webhook_confirms_payment_once(self):
        reference = self.start()[0].data["reference"]
        event = {"event": "charge.success", "data": {
            "reference": reference, "status": "success", "amount": naira(120_000), "currency": "NGN",
            "channel": "card", "id": 99887766, "paid_at": "2026-10-01T10:00:00.000Z"}}
        self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual(self.webhook(event).status_code, 200)  # retries are harmless
        payment = Payment.objects.get(reference=reference)
        self.assertEqual(payment.status, "successful")
        self.assertEqual(payment.external_reference, "99887766")
        self.assertEqual(Receipt.objects.filter(payment=payment).count(), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "paid")
        self.assertTrue(AuditLog.objects.filter(action="payment.online_confirmed").exists())

    def test_webhook_rejects_bad_signature(self):
        reference = self.start()[0].data["reference"]
        event = {"event": "charge.success", "data": {"reference": reference, "status": "success", "amount": 1}}
        self.assertEqual(self.webhook(event, secret="wrong").status_code, 400)
        self.assertEqual(Payment.objects.get(reference=reference).status, "pending")

    def test_verify_endpoint_after_redirect(self):
        reference = self.start()[0].data["reference"]
        with mock.patch("apps.fees.paystack.requests.request") as req:
            req.return_value = paystack_response({"reference": reference, "status": "success",
                                                  "amount": naira(120_000), "currency": "NGN", "channel": "ussd", "id": 1})
            response = APIClient().get(f"/api/v1/public/payments/verify/?reference={reference}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "successful")
        self.assertTrue(response.data["receipt_number"])
        self.assertEqual(response.data["invoice_balance_kobo"], 0)

    def test_gateway_failure_marks_payment_failed(self):
        with mock.patch("apps.fees.paystack.requests.request") as req:
            req.return_value = paystack_response({}, status=False, code=400)
            response = APIClient().post(f"/api/v1/public/pay/{self.token()}/initialize/",
                                        {"email": "p@example.com"}, format="json")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(Payment.objects.get(invoice=self.invoice).status, "failed")

    def test_cancelled_invoice_link_stops_working(self):
        token = self.token()
        services.cancel_invoice(self.invoice, reason="test", user=self.w.bursar)
        self.assertEqual(APIClient().get(f"/api/v1/public/pay/{token}/").status_code, 404)


@override_settings(PAYSTACK_SECRET_KEY="", DEBUG=True, PAYSTACK_SIMULATE=True)
class SimulatedPaymentTests(FeesTestCase):
    def test_simulated_flow_for_local_development(self):
        token = self.bursar().get(f"/api/v1/fees/invoices/{self.invoice.id}/pay-link/").data["url"].rsplit("/", 1)[-1]
        start = APIClient().post(f"/api/v1/public/pay/{token}/initialize/", {"email": "p@example.com"}, format="json")
        self.assertEqual(start.status_code, 201)
        self.assertTrue(start.data["simulated"])
        verify = APIClient().get(f"/api/v1/public/payments/verify/?reference={start.data['reference']}")
        self.assertEqual(verify.data["status"], "successful")


@override_settings(PAYSTACK_SECRET_KEY="")
class NotConfiguredTests(FeesTestCase):
    def test_online_payment_unavailable_without_keys(self):
        token = self.bursar().get(f"/api/v1/fees/invoices/{self.invoice.id}/pay-link/").data["url"].rsplit("/", 1)[-1]
        response = APIClient().post(f"/api/v1/public/pay/{token}/initialize/", {"email": "p@example.com"}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Payment.objects.exists())
