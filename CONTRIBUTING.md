# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate && python manage.py seed_demo
python manage.py test
```

## Workflow

* Branch from `main`: `feature/<short-name>` or `fix/<short-name>`.
* Small pull requests with a clear description. CI must pass (checks, migrations, tests, schema).
* Every new endpoint needs tests, including a row in the role matrix test (`apps/core/tests/test_permissions.py`).
* Commit migrations with the model change (`python manage.py makemigrations`).

## Conventions

**Views**
* Subclass `SchoolModelViewSet`, `SchoolReadOnlyViewSet` or use `RoleAccessMixin` (`apps/core`).
* Always declare `read_roles` and `write_roles`; use `action_roles` for custom actions.
* Restrict teachers in `get_queryset`, never only in the frontend.
* Keep views thin: validate, check access, call a service, return a response.
* Add `@extend_schema(tags=[...], summary=...)` so Swagger stays useful.

**Serializers**
* Use `SchoolPK` for every foreign key coming from the client.
* Read-only computed fields go in serializers; business rules go in services.

**Services**
* All business rules and state changes live in `services.py`, wrapped in `transaction.atomic`.
* Lock rows (`select_for_update`) when changing money or workflow state.
* Raise `rest_framework` exceptions (`ValidationError` for 400) or `apps.core.exceptions.WorkflowError` / `Conflict` (409) with a message a school user can act on.

**Money**
* Integers in kobo. Never floats. Format only for display (`apps.core.money.format_naira`).

**Audit**
* Standard CRUD is audited automatically. For custom actions call
  `record_audit(request, "thing.happened", obj, metadata={...})`.

**Naming**
* Endpoints: plural nouns, kebab-case actions (`/send-pay-link/`).
* Audit actions: `noun.past_tense_verb` (`payment.reversed`).

## Adding a V2 feature: checklist

- [ ] Model(s) inherit `SchoolOwnedModel`
- [ ] Service functions with transactions
- [ ] ViewSet with roles declared, teacher scoping if relevant
- [ ] Serializers using `SchoolPK`
- [ ] Router registration in the app's `urls.py`
- [ ] Tests: happy path, role matrix, cross-school isolation
- [ ] Docs: API_REFERENCE.md and, if it affects the frontend, FRONTEND_INTEGRATION.md
