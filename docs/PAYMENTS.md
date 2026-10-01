# Fees, payments and receipts

## The flow

```
Fee structure (per level, per term)
        │  generate-invoices
        ▼
Invoice per student ──adjustments──► total
        │
        ├── Online: parent opens pay link ─► Paystack checkout ─► webhook / verify ─┐
        │                                                                          ├─► Payment (successful)
        └── Offline: bursar records cash / transfer / POS / cheque ────────────────┘        │
                                                                                            ├─► Receipt (numbered PDF)
                                                                                            ├─► Invoice.recalculate() → balance, status
                                                                                            ├─► Audit log
                                                                                            └─► Receipt link to guardians (online payments)
```

## Money rules

* Integers in **kobo** everywhere. ₦1 = 100.
* Invoice `total = sum(lines) − discounts + surcharges` (never below 0). `amount_paid = sum(successful payments)`, where reversals are negative. `balance = total − amount_paid`.
* Status: `unpaid` (nothing paid), `part_paid`, `paid` (balance ≤ 0), `cancelled`.
* A payment can't be more than the current balance.
* Payments are **never edited or deleted**. To undo one, `POST fees/payments/{id}/reverse/` with a reason. This creates a negative payment linked to the original, and the invoice balance goes back up.
* An invoice with payments can't be cancelled. Reverse the payments first.
* Duplicate bank references are rejected for manual payments of the same method (prevents recording the same transfer twice).

## Bursar's setup each term

1. `POST fees/structures/` for each level with its items (Tuition, Books, PTA…).
2. `POST fees/structures/{id}/generate-invoices/`. Safe to repeat after adding late students; existing invoices are skipped.
3. Add scholarships and discounts: `POST fees/invoices/{id}/adjustments/`.
4. Send pay links: `POST fees/invoices/{id}/send-pay-link/` (SMS + email to guardians).

One-off invoices (late admission, special charge): `POST fees/invoices/`.

## Paystack setup

1. Create a Paystack account (the **school's own account** is recommended for V1; see "Who holds the money" below).
2. Copy the **test** secret and public keys from *Settings → API Keys & Webhooks* into `.env`:
   ```
   PAYSTACK_SECRET_KEY=sk_test_...
   PAYSTACK_PUBLIC_KEY=pk_test_...
   PAYSTACK_CALLBACK_URL=https://<frontend>/payments/complete
   ```
3. Set the **webhook URL** in the Paystack dashboard to
   `https://<your-api-domain>/api/v1/payments/paystack/webhook/`.
   For local testing, expose your server with a tunnel such as ngrok and use that URL.
4. Use Paystack's test cards to try payments.

### How an online payment is confirmed

* `POST public/pay/{token}/initialize/` creates a **pending** `Payment` with our reference (`PSK-...`) and calls Paystack `transaction/initialize`. The parent is redirected to `authorization_url`.
* Paystack then confirms in two ways, and both are handled:
  * **Webhook** `charge.success`. The `x-paystack-signature` header (HMAC-SHA512 of the raw body with the secret key) is verified; invalid signatures get `400`.
  * **Verify**: the frontend callback page calls `GET public/payments/verify/?reference=...`, which asks Paystack `transaction/verify`.
* Confirmation is **idempotent**. The payment row is locked, and if it is already successful nothing happens, so retries, duplicate webhooks and webhook-plus-verify all produce exactly one receipt.
* The amount Paystack reports is what gets recorded. If it differs from what was requested, the difference is flagged in `gateway_response.flags` and in the audit log for the bursar to review.
* Failed or abandoned transactions mark the payment `failed`.

### Local development without keys

With `DJANGO_DEBUG=true`, `PAYSTACK_SIMULATE=true` and no secret key:
* `initialize` returns `simulated: true`, and `authorization_url` points straight to your callback page.
* `verify` marks the payment successful.

This lets the frontend build the full flow before anyone has Paystack keys. It is ignored when `DEBUG` is false.

## Receipts

* Numbered per school: `RCT-000001`, … (prefix configurable in settings).
* Stores `amount_kobo` and `balance_after_kobo` at the time of payment.
* Staff: `GET fees/payments/{id}/receipt/` (PDF).
* Parents: `GET fees/payments/{id}/receipt-link/` gives a signed public link valid for 180 days (configurable). Online payments send this link to guardians automatically.

## Reports

* `GET fees/reports/outstanding/?term=` returns billed, collected, outstanding and collection rate per class, plus counts of paid, part-paid and owing.
* `GET fees/reports/collections/?date_from&date_to` returns money received by method and by day.
* The bursar dashboard adds today, this week, this month and the top 10 debtors.

## Who holds the money (decision for the team)

V1 assumes **each school uses its own Paystack account** (keys in this deployment's
environment). Collecting money on behalf of schools (one platform account plus payouts or
split payments) may bring regulatory duties, so get advice before doing that. For several
schools on one deployment, the next step is to store keys per school (encrypted) or use
Paystack subaccounts with split payments.

Who pays the gateway fee (school or parent) is also a school decision. V1 charges the
parent exactly the invoice amount, so the school absorbs the fee. Check Paystack's current pricing before quoting anything.
