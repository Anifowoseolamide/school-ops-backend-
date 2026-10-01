# Results and report cards

## Concepts

| Thing | One per | Holds |
|---|---|---|
| **Class result** | class per term | the class workflow status, class average, approvals |
| **Score sheet** | subject per class per term | the subject teacher, sheet status, return note |
| **Score** | student per sheet | CA1, CA2, exam, total, grade, remark |
| **Result summary** | student per class result | total, average, subjects, position, class size, comments |

## Term setup (admin)

1. Make sure the term is current and teacher assignments exist for the session.
2. `POST results/setup/` (optionally `{term}`). This creates a class result for every class and a score sheet for every assignment.
3. Run it again after adding classes or changing assignments. It's idempotent, and sheets not yet submitted pick up the new teacher.

## Score entry (subject teacher)

* `GET results/sheets/` lists my sheets with progress (`students`, `complete`, `missing`).
* `GET results/sheets/{id}/` returns one row per student, plus `maxima` and `can_edit`.
* `PUT results/sheets/{id}/scores/` with `{scores: [{student, ca1, ca2, exam}]}`. Send any subset; `null` clears a value; decimals allowed.
* The server validates each score against the school's maximums (default 20/20/60), computes `total` once all three are present, and looks up `grade` and `remark` from the grading scale.
* `POST results/sheets/{id}/submit/` requires every student to have all three scores. After submitting, the sheet is locked.

## Workflow

```
Sheet:   draft ──submit──► submitted ──(admin) return + note──► returned ──submit──► submitted

Class:   open ──(admin) begin-review──► in_review ──(principal) approve──► approved ──(principal) publish──► published
                  needs every sheet           ▲                               │                               │
                  submitted                   └──────(principal) send-back────┘                               │
                                              ▲                                                               │
                                              └─────────────(principal) unlock + reason (audited)─────────────┘
         Returning a sheet while the class is in_review moves the class back to open.
```

| Action | Who | From → To |
|---|---|---|
| `submit` (sheet) | subject teacher | draft/returned → submitted |
| `return` (sheet) | admin | submitted → returned (class in_review → open) |
| `begin-review` | admin | open → in_review |
| `approve` | principal | in_review → approved |
| `send-back` | principal | approved → in_review |
| `publish` | principal | approved → published |
| `unlock` | principal, reason required | published → in_review |

Wrong-state actions return **409** with a `detail` that explains what to do. Every
transition is written to the audit log.

## Totals, averages and positions

Computed on `begin-review`, `approve` and `publish`:

* **Total**: the sum of the student's subject totals.
* **Average**: total ÷ number of subjects with a total (2 decimal places, rounded half-up).
* **Position**: **standard competition ranking** on average, so ties share a position and the next one is skipped (1, 2, 2, 4).
* **Class size**: the number of students ranked.
* **Class average**: the mean of the student averages.
* The report card also shows each subject's class average and highest score.

## Grading

The default scale is WAEC-style A1 (75–100) to F9 (0–39), editable via `grade-bands/`.
A total gets the first band (highest first) where `total >= min_score`.

## Comments

* Form (class) teacher: `PATCH results/summaries/{id}/` `{"class_teacher_comment": "..."}`
* Principal: `PATCH results/summaries/{id}/` `{"principal_comment": "..."}`
* Allowed while the class is not published.

## Report cards

* Whole class: `GET results/class-results/{id}/report-cards/` (admin, principal). One PDF, one page per student, sorted by name.
* One student: `GET results/summaries/{id}/report-card/`.
* Before publishing, PDFs carry a **"DRAFT - NOT PUBLISHED"** watermark.
* Each card shows the school header, student details, attendance (days attended of days marked), a subject table (CA1, CA2, exam, total, grade, remark, class average, highest), total, average, position, class average, comments, signature lines, grading key, next term date and footer.
* **Parents:** after publishing, `GET results/summaries/{id}/share-link/` gives a signed link valid for 14 days (configurable), and `POST results/class-results/{id}/send-report-cards/` sends every guardian their child's link.
* **Hold for unpaid fees:** if `school/settings/` has `hold_report_cards_for_debtors: true`, the public link returns 403 while the student's term invoice has a balance. Staff can still download it.

## Tracking

* `GET results/missing/` lists unsubmitted sheets, grouped by teacher, with missing counts. It feeds the principal's "needs attention".
* `GET results/class-results/{id}/broadsheet/` returns every student's total in every subject.
