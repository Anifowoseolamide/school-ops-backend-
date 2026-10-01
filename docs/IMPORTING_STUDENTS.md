# Importing students from Excel or CSV

Schools usually keep their students in Excel. The import lets an admin upload that file
as it is, preview what will happen, and then create the students and their guardians.

## Steps

1. **Create the classes first** (`POST classes/`). Rows for classes that don't exist are rejected.
2. **Preview:**
   ```http
   POST /api/v1/students/imports/preview/
   Content-Type: multipart/form-data
   file=@register.xlsx
   column_mapping={"Code": "admission_number"}     (optional)
   ```
   Nothing is created. The response is a report:
   ```json
   {
     "import_id": 7,
     "status": "previewed",
     "column_mapping": {"admission_number": "Admission No", "last_name": "Surname", "classroom": "Class", "...": "..."},
     "unmapped_columns": ["S/N", "Religion"],
     "missing_required_columns": [],
     "total_rows": 312,
     "valid_rows": 305,
     "error_count": 7,
     "errors": [{"row": 14, "errors": ["Class 'JSS 3C' does not exist yet. Create it before importing."], "data": {...}}],
     "sample": [{"admission_number": "SSS/2026/1001", "first_name": "Chinedu", "classroom_name": "JSS 1A", "...": "..."}]
   }
   ```
   Show the admin the counts, the detected mapping and the problem rows (with spreadsheet row numbers).
3. **Commit:** `POST /api/v1/students/imports/{import_id}/commit/` creates the valid rows in
   one transaction. Rows with problems are skipped and listed in `error_rows`. An import
   can be committed only once (a second attempt returns 409). Fix the skipped rows in the
   file and import them again.

## File format

* `.csv` (UTF-8 or Windows encodings) or `.xlsx`. First sheet only. Max 5 MB and 5,000 rows.
* The header row is detected automatically. Title rows above it are skipped.
* Column names are matched loosely (case, spaces and punctuation are ignored).

| Field | Required | Recognised headers (examples) |
|---|---|---|
| `admission_number` | ✓ | Admission No, Adm No, Reg No, Registration Number, Student ID |
| `first_name` | ✓ (or full name) | First Name, Firstname, Given Name |
| `last_name` | ✓ (or full name) | Surname, Last Name, Family Name |
| `middle_name` | | Middle Name, Other Names |
| `full_name` | instead of first/last | Name, Full Name, Student Name. Read as **"Surname Firstname Middlename"**, or "Surname, Firstname" |
| `classroom` | ✓ | Class, Class Arm, Current Class. Values like `JSS 1A`, `jss1a`, `JSS1-A`, `SSS 2 Gold`, `SS3B` |
| `gender` | | Gender, Sex: `M`/`F`/`Male`/`Female` |
| `date_of_birth` | | Date of Birth, DOB: `DD/MM/YYYY`, `YYYY-MM-DD`, or Excel dates |
| `admission_date` | | Admission Date |
| `address` | | Address, Home Address |
| `guardian_name` | | Parent Name, Guardian Name, Parent, Father Name… |
| `guardian_relationship` | | Relationship |
| `guardian_phone` | | Parent Phone, Phone, Phone Number, GSM, Mobile… |
| `guardian_email` | | Parent Email, Email |

A sample file is in [`docs/samples/students_sample.csv`](samples/students_sample.csv).

## Cleaning rules

* Names in ALL CAPS or all lowercase are converted to Title Case.
* Phone numbers: spaces and dashes are removed, `+234…`/`234…` becomes `0…`, and a 10-digit number missing its leading zero (Excel often drops it) gets the zero back.
* **Siblings:** rows with the same guardian phone share one guardian record, including guardians already in the system.
* Titles in guardian names are kept: "Mrs Ngozi Okafor" becomes first name "Mrs Ngozi", last name "Okafor".

## Rejected rows

* Missing admission number, or one that already exists in the school or appears twice in the file.
* Missing names.
* Class missing, unreadable, or not created yet.
* Gender or dates that can't be read.
* A phone number that doesn't look like a phone number.

## Overriding column detection

If a header isn't recognised, pass `column_mapping` as a JSON object `{"Header in file": "field"}`:

```json
{"Code": "admission_number", "Group": "classroom", "Mum's Line": "guardian_phone"}
```
