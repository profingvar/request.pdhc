# request.pdhc — Changed Files Registry

All edited files are noted here with full path, per Rule 17.

---

| Date       | File | Action |
|------------|------|--------|
| 2026-03-20 | `request.pdhc/readme.md` | Created |
| 2026-03-20 | `request.pdhc/progress.md` | Created |
| 2026-03-20 | `request.pdhc/changed_files.md` | Created |
| 2026-03-20 | `request.pdhc/CLAUDE.md` | Created |
| 2026-03-20 | `request.pdhc/.gitignore` | Created |
| 2026-03-20 | `request.pdhc/start.sh` | Created |
| 2026-03-20 | `request.pdhc/stop.sh` | Created |
| 2026-03-20 | `request.pdhc/pdhc_markdown_layout_standard.md` | Copied |
| 2026-03-20 | `request.pdhc/repo_css.md` | Copied |
| 2026-03-20 | `gateway/.env` | Created |
| 2026-03-20 | `gateway/.env.example` | Created |
| 2026-03-20 | `gateway/requirements.txt` | Created |
| 2026-03-20 | `gateway/Dockerfile` | Created |
| 2026-03-20 | `gateway/docker-compose.yml` | Created |
| 2026-03-20 | `gateway/entrypoint.sh` | Created |
| 2026-03-20 | `gateway/app/__init__.py` | Created |
| 2026-03-20 | `gateway/app/config.py` | Created |
| 2026-03-20 | `gateway/app/models/__init__.py` | Created |
| 2026-03-20 | `gateway/app/models/dispatch_models.py` | Created |
| 2026-03-20 | `gateway/app/models/audit_models.py` | Created |
| 2026-03-20 | `gateway/app/models/export_models.py` | Created |
| 2026-03-20 | `gateway/app/services/__init__.py` | Created |
| 2026-03-20 | `gateway/app/services/auth_service.py` | Created |
| 2026-03-20 | `gateway/app/services/patient_service.py` | Created |
| 2026-03-20 | `gateway/app/services/careplan_service.py` | Created |
| 2026-03-20 | `gateway/app/services/parse_service.py` | Created |
| 2026-03-20 | `gateway/app/services/csv_service.py` | Created |
| 2026-03-20 | `gateway/app/services/dispatch_service.py` | Created |
| 2026-03-20 | `gateway/app/services/provider_service.py` | Created |
| 2026-03-20 | `gateway/app/services/audit_service.py` | Created |
| 2026-03-20 | `gateway/app/middleware/__init__.py` | Created |
| 2026-03-20 | `gateway/app/middleware/auth_middleware.py` | Created |
| 2026-03-20 | `gateway/app/middleware/cors.py` | Created |
| 2026-03-20 | `gateway/app/middleware/rate_limit.py` | Created |
| 2026-03-20 | `gateway/app/api/__init__.py` | Created |
| 2026-03-20 | `gateway/app/api/auth.py` | Created |
| 2026-03-20 | `gateway/app/api/patients.py` | Created |
| 2026-03-20 | `gateway/app/api/careplans.py` | Created |
| 2026-03-20 | `gateway/app/api/dispatch.py` | Created |
| 2026-03-20 | `gateway/app/api/providers.py` | Created |
| 2026-03-20 | `gateway/app/api/export.py` | Created |
| 2026-03-20 | `gateway/app/api/capability.py` | Created |
| 2026-03-20 | `gateway/app/routes/__init__.py` | Created |
| 2026-03-20 | `gateway/app/routes/main.py` | Created |
| 2026-03-20 | `gateway/app/routes/patients.py` | Created |
| 2026-03-20 | `gateway/app/routes/careplans.py` | Created |
| 2026-03-20 | `gateway/app/routes/dispatch.py` | Created |
| 2026-03-20 | `gateway/app/routes/export.py` | Created |
| 2026-03-20 | `gateway/app/static/css/pdhc.css` | Copied |
| 2026-03-20 | `gateway/app/templates/base.html` | Created |
| 2026-03-20 | `gateway/app/templates/dashboard.html` | Created |
| 2026-03-20 | `gateway/app/templates/patients/list.html` | Created |
| 2026-03-20 | `gateway/app/templates/patients/view.html` | Created |
| 2026-03-20 | `gateway/app/templates/patients/create.html` | Created |
| 2026-03-20 | `gateway/app/templates/patients/edit.html` | Created |
| 2026-03-20 | `gateway/app/templates/careplans/list.html` | Created |
| 2026-03-20 | `gateway/app/templates/careplans/view.html` | Created |
| 2026-03-20 | `gateway/app/templates/careplans/readout.html` | Created |
| 2026-03-20 | `gateway/app/templates/dispatch/form.html` | Created |
| 2026-03-20 | `gateway/app/templates/dispatch/receipt.html` | Created |
| 2026-03-20 | `gateway/app/templates/export/preview.html` | Created |
| 2026-03-20 | `gateway/app/templates/export/download.html` | Created |
| 2026-03-20 | `gateway/tests/conftest.py` | Created |
| 2026-03-20 | `gateway/tests/test_app_factory.py` | Created |
| 2026-03-20 | `gateway/tests/test_auth.py` | Created |
| 2026-03-20 | `gateway/tests/test_parse.py` | Created |
| 2026-03-20 | `gateway/tests/test_csv_export.py` | Created |
| 2026-03-20 | `gateway/tests/test_patients.py` | Created |
| 2026-03-20 | `gateway/tests/test_careplans.py` | Created |
| 2026-03-20 | `gateway/tests/test_dispatch.py` | Created |
| 2026-03-20 | `gateway/tests/test_providers.py` | Created |
| 2026-03-20 | `gateway/tests/test_all_endpoints.py` | Created |
| 2026-03-20 | `gateway/app/api/requests.py` | Created |
| 2026-03-20 | `gateway/app/services/request_feed_service.py` | Created |
| 2026-03-20 | `gateway/tests/test_request_feed.py` | Created |
| 2026-03-20 | `gateway/app/models/dispatch_models.py` | Modified — added `provider_status`, `provider_status_updated_at`, index on `provider_guid` |
| 2026-03-20 | `gateway/app/middleware/auth_middleware.py` | Modified — added X-API-Key authentication |
| 2026-03-20 | `gateway/app/services/auth_service.py` | Modified — added `validate_api_key()` |
| 2026-03-20 | `gateway/app/api/capability.py` | Modified — added request-feed and status-update operations |
| 2026-03-20 | `gateway/app/__init__.py` | Modified — registered `requests_bp` blueprint |
| 2026-03-20 | `gateway/migrations/versions/837810485062_*.py` | Generated — provider_status fields and provider_guid index |
| 2026-03-20 | `subscription_design copy.md` | Modified — annotated with implementation details |
| 2026-03-24 | `gateway/app/routes/service_requests.py` | Updated — added org guard to `create_view` blocking org-less professionals |
| 2026-03-24 | `gateway/app/models/security_models.py` | Created — ProviderAccessToken (bcrypt-hashed PAT) and DataExchangeGrant (HMAC composite key) models |
| 2026-03-24 | `gateway/app/services/pat_service.py` | Created — PAT lifecycle: issue, validate, revoke, list |
| 2026-03-24 | `gateway/app/services/grant_service.py` | Created — HMAC grant lifecycle: issue, validate, use, revoke |
| 2026-03-24 | `gateway/app/services/provider_feed_service.py` | Created — metadata-only feed listing + FHIR bundle download with auto-grant |
| 2026-03-24 | `gateway/app/services/report_service.py` | Created — report submission with full composite key validation chain |
| 2026-03-24 | `gateway/app/api/provider.py` | Created — provider-facing API: feed, download, report, receipt ack |
| 2026-03-24 | `gateway/app/api/admin_tokens.py` | Created — admin PAT management API: issue, list, revoke |
| 2026-03-24 | `gateway/app/models/audit_models.py` | Modified — added `data_subject_guid` column (indexed) for GDPR patient tracking |
| 2026-03-24 | `gateway/app/services/audit_service.py` | Modified — added `data_subject_guid` param, auto-extract from details |
| 2026-03-24 | `gateway/app/middleware/auth_middleware.py` | Modified — added `_check_provider_token()`, `requires_provider_token()` decorator, PAT auth in `requires_auth` |
| 2026-03-24 | `gateway/app/services/push_service.py` | Modified — resolves endpoint from PAT records, issues grant before push, adds grant_token in bundle meta |
| 2026-03-24 | `gateway/app/config.py` | Modified — added HMAC_SECRET, PAT_DEFAULT_EXPIRY_DAYS, PROVIDER_GRANT_EXPIRY_HOURS, PROVIDER_GRANT_MAX_USES, PUSH_TIMEOUT_SECONDS |
| 2026-03-24 | `gateway/requirements.txt` | Modified — added `bcrypt>=4.1` |
| 2026-03-24 | `gateway/app/__init__.py` | Modified — registered security_models import, provider_bp and admin_tokens_bp blueprints |
| 2026-03-25 | `gateway/app/__init__.py` | Modified — enhanced /api/health to return DB status (connected/unavailable) |
