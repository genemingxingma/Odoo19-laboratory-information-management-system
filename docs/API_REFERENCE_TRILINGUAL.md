# Laboratory API Reference (CN / EN / TH)

This package is optimized for both human integrators and AI code generation.

## 1. Documents in this folder

- `docs/openapi/external_api_v1.yaml`: OpenAPI 3.0 for external institution REST API.
- `docs/openapi/interface_api_v1.yaml`: OpenAPI 3.0 for LIS/HIS interface channel API.
- `docs/postman/LIS_External_API.postman_collection.json`: Postman collection (external + interface).

## 2. Quick integration checklist

### 中文
1. 在后台创建 `Interface Endpoint`，协议使用 `REST`（外部机构API）或 `HL7/FHIR/REST`（接口通道）。
2. 开启认证（推荐 `API Key` 或 `Bearer`），并配置 `external_api_enabled`。
3. 配置机构范围：`external_partner_id`、`external_company_id`。
4. 先调用“创建申请”接口，再按申请号/样本号轮询状态。
5. 样本状态到 `verified/reported` 后下载 PDF。

### English
1. Create an `Interface Endpoint` in backend with protocol `REST` (external institution API) or `HL7/FHIR/REST` (interface channel).
2. Enable authentication (`API Key` or `Bearer` recommended) and `external_api_enabled`.
3. Configure data scope by `external_partner_id` and `external_company_id`.
4. Call create-request first, then poll by request number or accession.
5. Download PDF only after sample reaches `verified` or `reported`.

### ไทย
1. สร้าง `Interface Endpoint` ใน backend โดยใช้ protocol `REST` (External API) หรือ `HL7/FHIR/REST` (ช่องทาง interface)
2. เปิดใช้งานการยืนยันตัวตน (`API Key` หรือ `Bearer`) และ `external_api_enabled`
3. ตั้งค่า scope ข้อมูลด้วย `external_partner_id` และ `external_company_id`
4. เรียก API สร้างคำขอก่อน แล้วค่อย polling ด้วย request number/accession
5. ดาวน์โหลด PDF ได้เมื่อ sample อยู่สถานะ `verified` หรือ `reported`

## 3. Authentication

Supported auth configured on endpoint:
- `X-API-Key: <key>`
- `Authorization: Bearer <token>`
- `Authorization: Basic <base64(username:password)>`

If endpoint auth is set to `none`, requests are accepted without credentials (not recommended for production).

## 4. External Institution REST API

Base path:
- `/lab/api/v1/{endpoint_code}`

### 4.1 Create test request
- `POST /requests`
- Route type in Odoo: `json`
- Content-Type: `application/json`

Request payload contract:
- `lines` (required, array)
- `external_uid` (optional but strongly recommended for idempotency)
- `patient` (optional object)
- `physician` (optional object)
- `priority`, `clinical_note`, `preferred_template_code` (optional)
- `attachments` (optional, array of base64 files)
- `dynamic_forms` (optional, array of form responses)

Attachment object:
- `name` or `filename` (required)
- `content_base64` or `datas` (required)
- `mimetype` (optional)

Line rules:
- `line_type` must be `service` or `profile`
- if `service` -> `service_code` required
- if `profile` -> `profile_code` required
- `specimen_ref` default is `SP1`
- `specimen_sample_type` default is `swab`
- `quantity` default is `1`

Important:
- Specimen type is controlled per line (`specimen_sample_type`).
- Top-level `sample_type` should not be used by new integrations.
- Each attachment max size is `10 MB`.
- If a selected service/panel requires dynamic forms, missing required answers will be rejected.
- API now supports extended patient/physician fields and will match-or-create records under `external_company_id`.

Patient input (extended, key fields):
- identity: `id`, `identifier`, `patient_id_no`, `id_no`, `passport_no`, `passport`
- demographics: `name`, `gender`, `birthdate`, `phone`, `email`, `lang`
- address: `street`, `street2`, `city`, `state_id|state_code|state`, `zip`, `country_id|country_code|country`
- emergency/medical: `emergency_contact_*`, `allergy_history`, `past_medical_history`, `medication_history`, `pregnancy_status`, `breastfeeding`, `insurance_*`, `informed_consent_*`, `note`

Physician input (extended, key fields):
- identity: `id`, `code`, `partner_ref` (alias of code), `license_no`, `name`
- profile: `title`, `specialty`, `phone`, `email`
- organization: `department_id|department_code`, `institution_id|institution_ref|institution_name`
- notification/note: `notify_by_email`, `notify_by_sms`, `note`

Dynamic form payload example:
```json
{
  "dynamic_forms": [
    {
      "form_code": "STD_PRETEST_QA",
      "answers": {
        "recent_exposure": "yes",
        "symptoms": "no",
        "clinical_note": "No known exposure in last 14 days",
        "consent": true
      }
    }
  ]
}
```

Successful response shape:
```json
{
  "ok": true,
  "deduplicated": false,
  "request": {
    "id": 320,
    "request_no": "TRQ2602-00320",
    "state": "submitted",
    "patient": {
      "id": 15,
      "name": "API Patient A",
      "identifier": "API-9001",
      "passport_no": "P12345678",
      "gender": "female",
      "birthdate": "1992-01-01",
      "age_display": "34 years 1 months 0 days"
    },
    "physician": {
      "id": 12,
      "name": "Dr. External",
      "code": "PHY-001",
      "license_no": "LIC-9999",
      "department": {"code": "OPD", "name": "Outpatient"}
    },
    "samples": []
  }
}
```

### 4.2 Query request
- `GET /requests/{request_no}`
- Returns request header + patient summary + sample list.
- Also returns attachment summary list (`id/name/mimetype/size`).

### 4.2.1 Upload attachments to existing request
- `POST /requests/{request_no}/attachments`
- Supports:
  - `application/json` with `attachments` base64 payload
  - `multipart/form-data` with repeated `files` fields
- Response includes uploaded attachment metadata.

### 4.3 Query sample results
- `GET /samples/{accession}/results`
- Returns sample state + analysis lines + optional `ai_interpretation`.
- `sample.patient` now returns a structured object:
  - `id`, `name`, `identifier`, `passport_no`

### 4.3.1 Push sample results (REST)
- `POST /results`
- `POST /samples/{accession}/results`
- Requires endpoint protocol `REST`.
- Requires endpoint option `Allow Result Push = enabled`.
- Payload:
```json
{
  "external_uid": "HIS-RES-20260226-0001",
  "accession": "ACC2602-00318",
  "results": [
    {"service_code": "HPV16", "result": "31.8", "note": "Ct from analyzer"},
    {"service_code": "HPV18", "result": "0", "note": "not detected"}
  ]
}
```

### 4.3.2 Push sample results (HL7 ORU)
- `POST /hl7/oru`
- Requires endpoint protocol `HL7 v2.x`.
- Body is raw HL7 ORU text.
- Returns HL7 ACK text (`AA/AE/AR`).

### 4.4 Download sample report PDF
- `GET /samples/{accession}/report/pdf`
- Binary PDF stream.
- Returns `409 report_not_ready` before state is `verified/reported`.

### 4.5 Query sample types metadata
- `GET /meta/sample_types`
- Returns currently active sample types that can be used in request payload and specimen lines.
```json
{
  "ok": true,
  "sample_types": [
    {"code": "swab", "name": "Swab", "is_default": true}
  ]
}
```

### 4.6 Query services metadata
- `GET /meta/services`
- Returns active service catalog (`code`, `name`, `sample_type`).
```json
{
  "ok": true,
  "services": [
    {"code": "STD_CT", "name": "Chlamydia Trachomatis PCR", "sample_type": "swab"}
  ]
}
```

### 4.7 Query profiles metadata
- `GET /meta/profiles`
- Returns active profile catalog (`code`, `name`, `sample_type`).
```json
{
  "ok": true,
  "profiles": [
    {"code": "STD7-7", "name": "STD 7 Panel", "sample_type": "swab"}
  ]
}
```

## 5. LIS/HIS Interface Channel API

### 5.1 Inbound JSON-RPC
- `POST /lab/interface/inbound/{endpoint_code}`
- Route type: `jsonrpc`
- Body fields:
  - `message_type` (e.g. `order`)
  - `payload` (object)
  - `external_uid` (optional)
  - `raw_message` (optional)

Response includes ACK semantics:
- `ack_code`: `AA` (accepted), `AE` (error), `AR` (rejected)

### 5.2 Inbound raw message
- `POST /lab/interface/inbound/{endpoint_code}/raw`
- Route type: `http`
- Protocol behavior:
  - `hl7v2`: returns HL7 ACK text
  - `fhir`: returns FHIR OperationOutcome JSON
  - `rest`: treats body as JSON payload

### 5.3 Outbound ACK receiver
- `POST /lab/interface/outbound/{endpoint_code}/ack`
- Route type: `jsonrpc`
- Fields: `ack_code`, `job_name`/`job_id`, `external_uid`, `message`, `payload`

## 6. Common error codes

External API errors:
- `endpoint_not_found`
- `endpoint_protocol_not_rest`
- `unauthorized`
- `request_push_disabled`
- `result_query_disabled`
- `report_download_disabled`
- `metadata_query_disabled`
- `lines_required`
- `invalid_line_type`
- `service_not_found`
- `profile_not_found`
- `request_not_found`
- `sample_not_found`
- `report_not_ready`
- `required_dynamic_form_missing`
- `required_dynamic_field_missing`
- `dynamic_form_not_found`

Interface API errors:
- `endpoint_not_found`
- `direction_not_allowed`
- `unauthorized`
- runtime exceptions returned as `error`

## 7. AI-friendly field dictionary

### Request states
- `draft`: created but not submitted.
- `submitted`: request submitted to lab workflow.
- `approved`: request reviewed/approved.
- `done`/`cancel`: terminal states depending on workflow.

### Sample states
- `draft` -> `received` -> `in_progress` -> `verified` -> `reported`

### Result line fields
- `service_code`: service unique code.
- `result_value`: textual/numeric result value.
- `binary_interpretation`: normalized positive/negative style interpretation.
- `unit`, `ref_min`, `ref_max`: reference range metadata.

## 8. cURL examples

Create request:
```bash
curl -X POST "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/requests" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026" \
  -d '{
    "external_uid": "HIS-REQ-20260222-9001",
    "priority": "routine",
    "patient": {"name": "API Patient A", "identifier": "API-9001", "gender": "female"},
    "lines": [{"line_type": "service", "service_code": "STD_CT", "specimen_ref": "SP1", "specimen_sample_type": "swab"}]
  }'
```

Query request:
```bash
curl -X GET "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/requests/TRQ2602-00320" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026"
```

Query sample results:
```bash
curl -X GET "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/samples/ACC2602-00318/results" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026"
```

Push sample results (REST):
```bash
curl -X POST "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/results" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026" \
  -d '{
    "external_uid": "HIS-RES-20260226-0001",
    "accession": "ACC2602-00318",
    "results": [{"service_code":"STD_CT","result":"7.2","note":"Analyzer A1"}]
  }'
```

Push HL7 ORU:
```bash
curl -X POST "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/hl7/oru" \
  -H "Content-Type: text/plain" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026" \
  --data-binary $'MSH|^~\\&|HIS|HOSP|LIS|LAB|202602261130||ORU^R01|MSG00001|P|2.5\\rPID|||P001||DOE^JANE\\rOBR|1||ACC2602-00318|STD7\\rOBX|1|NM|STD_CT||7.2\\r'
```

Download PDF:
```bash
curl -X GET "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/samples/ACC2602-00318/report/pdf" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026" \
  -o report.pdf
```

Query sample types metadata:
```bash
curl -X GET "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/meta/sample_types" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026"
```

Query services metadata:
```bash
curl -X GET "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/meta/services" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026"
```

Query profiles metadata:
```bash
curl -X GET "http://127.0.0.1:8069/lab/api/v1/ext_hospital_demo/meta/profiles" \
  -H "X-API-Key: DEMO-HOSP-API-KEY-2026"
```
