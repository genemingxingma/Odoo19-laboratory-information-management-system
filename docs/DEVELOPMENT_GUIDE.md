# Development Guide

## 1. Scope

This guide targets developers maintaining `laboratory_management` on Odoo 19.

## 2. Core Architecture

- `models/lab_test_request.py`: request header, request lines, lifecycle, quotation/billing links.
- `models/lab_sample.py`: accession/sample lifecycle and report state flow.
- `models/lab_service.py` + `models/lab_profile.py`: test catalog (service/panel).
- `models/lab_patient.py`: lab-native patient master model.
- `models/lab_physician.py`: lab-native physician master model.
- `models/lab_dynamic_form.py`: dynamic forms, form fields, request responses.
- `controllers/portal.py`: portal request/report pages.
- `controllers/external_api.py`: external REST API for institutions/hospitals.

## 3. New Capability Baseline (19.0.2.0.22)

### 3.1 Dynamic Form Binding

- Services and panels can require one or more dynamic forms.
- On request submission, required forms are validated and stored as response records.
- Same logic is reused by portal submit and external API submit.

### 3.2 Request Attachments

- Attachments can be added in:
  - Portal request creation
  - Internal request workbench
  - External API (`POST /requests` and `POST /requests/{no}/attachments`)

### 3.3 Lab-native Master Data

- Patient/physician data are moved to lab models instead of relying only on `res.partner`.
- Request/sample links use lab models where applicable.

## 4. Data Migration / Upgrade Risk Notes

When upgrading from older schema versions, ensure:

- Legacy foreign keys referencing removed partner-based ids are cleaned.
- `lab_test_request.patient_id` and related fields do not keep dangling ids.
- If the database has severe legacy divergence, prefer clean uninstall/reinstall.

## 5. Local Development Workflow

1. Update code in this repository.
2. Upgrade module:
   - `python <odoo-bin> -c <conf> -d <db> -u laboratory_management --stop-after-init`
3. Start service and verify:
   - menu load
   - request create
   - sample lifecycle
   - report render (H5/PDF)
   - AI interpretation pipeline

## 6. Remote Deployment Workflow

1. Push code to GitHub.
2. Sync module directory on server.
3. Stop Odoo service.
4. Upgrade module with `--stop-after-init --no-http`.
5. Start Odoo service.
6. Validate endpoint/UI health.

If upgrade fails due to historical schema conflicts, run clean uninstall/reinstall on target DB.

## 7. Coding and i18n Rules

- Source strings in code must be English.
- Use translation files for Chinese and Thai.
- Keep business logic data-driven; avoid hard-coded medical catalog values.

## 8. Regression Checklist

- Request type visibility and service/panel scope filtering.
- Portal request/report card layout and icons.
- Result release and PDF download.
- Attachment upload/download permissions.
- Multi-company isolation record rules.
