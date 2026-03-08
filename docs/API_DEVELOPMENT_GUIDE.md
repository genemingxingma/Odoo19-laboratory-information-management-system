# Laboratory API Development Guide

This document is for developers maintaining or extending the API layer.

## 1. Scope

Integration APIs in this module are implemented in two controllers only:
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/controllers/external_api.py`
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/controllers/interface_api.py`

Explicitly out of scope:
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/controllers/portal.py`
- backend form views, menu actions, and website page routes

## 2. API Families

### 2.1 External Institution API

Purpose:
- create test requests
- upload request attachments
- query requests and sample results
- download report PDFs
- query service/profile/sample-type metadata
- push sample results through REST or HL7 ORU

Base path:
- `/lab/api/v1/{endpoint_code}`

Main route types:
- `type="json"` for request creation
- `type="http"` for all other endpoints

### 2.2 Interface Channel API

Purpose:
- lower-level LIS/HIS/instrument integration
- inbound JSON-RPC messages
- inbound raw HL7/FHIR/REST payloads
- outbound ACK callback registration

Base path:
- `/lab/interface`

Main route types:
- `type="jsonrpc"` for `/inbound/{endpoint_code}` and `/outbound/{endpoint_code}/ack`
- `type="http"` for `/inbound/{endpoint_code}/raw`

## 3. Authentication Model

Authentication is endpoint-driven and shared by both API families.

Supported values of `lab.interface.endpoint.auth_type`:
- `none`
- `api_key`
- `bearer`
- `basic`

Headers expected by current implementation:
- API key: `X-API-Key: <key>`
- Bearer: `Authorization: Bearer <token>`
- Basic: `Authorization: Basic <base64(username:password)>`

Important implementation note:
- `auth_type = none` is allowed by code today.
- Keep it for local testing only.
- Production guidance remains API key or bearer.

## 4. Capability Flags

Route availability is not controlled only by authentication. It also depends on endpoint capability flags.

Important flags in `lab.interface.endpoint` used by `external_api.py`:
- `external_api_enabled`
- `external_allow_request_push`
- `external_allow_result_push`
- `external_allow_result_query`
- `external_allow_report_download`
- `external_allow_metadata_query`
- `external_auto_submit_request`

Other route guards:
- `endpoint.protocol`
- `endpoint.direction`
- endpoint company scope
- request-type catalog restrictions

## 5. Controller Conventions

### 5.1 `external_api.py`

Key conventions:
- use `_lookup_endpoint(...)` before any business logic
- route returns are mixed intentionally:
  - `type="json"` route returns Python dict
  - `type="http"` route returns `request.make_response(...)` wrappers through `_json_response(...)`
- use endpoint company scoping through `.with_company(endpoint.external_company_id)`
- use endpoint-scoped domains for request/sample lookup
- use savepoints around create flows that can fail after validation

### 5.2 `interface_api.py`

Key conventions:
- JSON-RPC handlers return dict payloads with ACK semantics
- raw inbound handler returns protocol-native responses:
  - HL7 v2 -> plain text HL7 ACK
  - non-HL7 path -> FHIR-style `OperationOutcome` JSON body
- endpoint audit logging is written through `lab.interface.audit.log`

## 6. Current External Endpoint Inventory

Implemented routes in `external_api.py`:
- `POST /lab/api/v1/{endpoint_code}/requests`
- `POST /lab/api/v1/{endpoint_code}/requests/{request_no}/attachments`
- `GET /lab/api/v1/{endpoint_code}/requests/{request_no}`
- `POST /lab/api/v1/{endpoint_code}/results`
- `POST /lab/api/v1/{endpoint_code}/samples/{accession}/results`
- `GET /lab/api/v1/{endpoint_code}/samples/{accession}/results`
- `POST /lab/api/v1/{endpoint_code}/hl7/oru`
- `GET /lab/api/v1/{endpoint_code}/samples/{accession}/report/pdf`
- `GET /lab/api/v1/{endpoint_code}/meta/sample_types`
- `GET /lab/api/v1/{endpoint_code}/meta/services`
- `GET /lab/api/v1/{endpoint_code}/meta/profiles`

Implemented routes in `interface_api.py`:
- `POST /lab/interface/inbound/{endpoint_code}`
- `POST /lab/interface/inbound/{endpoint_code}/raw`
- `POST /lab/interface/outbound/{endpoint_code}/ack`

## 7. Payload Rules That Matter

### 7.1 Request creation

Request body uses these top-level keys:
- `external_uid`
- `requested_collection_date`
- `priority`
- `clinical_note`
- `preferred_template_code`
- `patient`
- `physician`
- `lines`
- `attachments`
- `dynamic_forms`

Important business rules:
- `lines` is mandatory
- `line_type` must be `service` or `profile`
- `specimen_sample_type` is currently mandatory per line
- `quantity` is normalized to `1` in current implementation
- request type is derived from endpoint-linked institution partner presence
- service requests reject `profile_only = True` services
- service/profile availability is filtered by request-type catalog restrictions

### 7.2 Dynamic form payload

Current implementation expects an object keyed by `form.code`.

Example:
```json
{
  "dynamic_forms": {
    "STD_PRETEST_QA": {
      "recent_exposure": "yes",
      "symptoms": "no",
      "consent": true
    }
  }
}
```

This is validated by:
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/models/lab_dynamic_form.py`
- method: `validate_dynamic_form_payload(self, forms, payload)`

It is not an array in current code.

### 7.3 Attachments

Supported request attachment upload modes:
- base64 JSON payload
- multipart form upload

Validation rules:
- filename and binary payload are required
- max attachment size is `10 MB`
- invalid base64 is rejected

### 7.4 Result push

REST result push payload requires:
- accession in body or path
- non-empty `results`
- each result line must include `service_code` and `result`

HL7 ORU result push expects raw HL7 text in the request body.

## 8. Error Contract

The module uses business error codes rather than only HTTP status messages.

Common external API error codes:
- `endpoint_not_found`
- `endpoint_protocol_not_allowed`
- `unauthorized`
- `direction_not_allowed`
- `request_push_disabled`
- `result_push_disabled`
- `result_query_disabled`
- `report_download_disabled`
- `metadata_query_disabled`
- `lines_required`
- `invalid_line_type`
- `specimen_sample_type_required`
- `invalid_specimen_sample_type`
- `service_not_found`
- `profile_not_found`
- `service_not_allowed_for_request_type`
- `profile_not_allowed_for_request_type`
- `dynamic_form_required`
- `request_create_failed`
- `invalid_json`
- `attachments_required`
- `invalid_attachment_payload`
- `attachment_name_or_data_missing`
- `attachment_decode_failed`
- `attachment_too_large`
- `sample_not_found`
- `request_not_found`
- `report_not_ready`

Important rule for documentation writers:
- document both HTTP status and JSON body error code
- integrations often branch on the body error code, not only status

## 9. Known Implementation Behaviors

These are intentional or at least current behaviors that documentation must match:
- request creation uses `type="json"`, not plain HTTP JSON
- `auth_type = none` is allowed
- request query availability is controlled by `external_allow_result_query`
- sample result query returns AI interpretation only if `ai_portal_visible` is true
- report PDF endpoint first tries cached attachment and falls back to QWeb rendering
- raw interface endpoint returns FHIR-style outcome JSON for non-HL7 success/failure cases

## 10. Extension Checklist

Before adding a new endpoint:
1. decide whether it belongs to `external_api.py` or `interface_api.py`
2. define route type correctly: `json`, `http`, or `jsonrpc`
3. add capability-flag checks if the feature can be disabled per endpoint
4. add company scoping
5. return stable business error codes
6. update both OpenAPI files if contract changes
7. update both human docs:
   - `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/API_REFERENCE_TRILINGUAL.md`
   - `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/EXTERNAL_API_GUIDE_TRILINGUAL.md`
8. add or update Postman collection if request shape changed
9. test against a real Odoo database, not only static lint

## 11. Validation Checklist

Minimum validation for API doc changes:
- YAML parses cleanly
- route inventory matches controller decorators
- documented auth methods match runtime code
- documented payload shape matches validator implementation
- documented error codes match controller returns
- examples do not use fields rejected by current code

## 12. Primary Documentation Files

Machine-readable:
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/openapi/external_api_v1.yaml`
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/openapi/interface_api_v1.yaml`

Human-readable:
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/API_REFERENCE_TRILINGUAL.md`
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/EXTERNAL_API_GUIDE_TRILINGUAL.md`
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/API_DEVELOPMENT_GUIDE.md`
