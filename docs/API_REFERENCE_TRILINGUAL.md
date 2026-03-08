# Laboratory API Reference (CN / EN / TH)

This reference is aligned to the current implementation in:
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/controllers/external_api.py`
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/controllers/interface_api.py`

It is intended for both human integrators and AI coding agents.

Scope note:
- This document covers integration APIs only.
- Website portal routes in `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/controllers/portal.py` are not part of the external integration contract.

## 1. API Families

### 中文
系统目前有两类 API，不要混用：
1. `External Institution API`
   - 用于医院、机构、第三方平台与 LIS 进行业务对接
   - 功能：创建申请、上传申请附件、查询申请、查询结果、下载 PDF、拉取元数据、推送 REST/HL7 结果
2. `Interface Channel API`
   - 用于更底层的 LIS/HIS/仪器接口通道
   - 功能：JSON-RPC 入站、Raw HL7/FHIR/REST 入站、出站 ACK 回调

### English
There are currently two API families. They serve different purposes:
1. `External Institution API`
   - For hospitals, institutions, partner platforms, and external ordering systems
   - Functions: create request, upload request attachments, query request, query results, download PDF, fetch metadata, push REST/HL7 results
2. `Interface Channel API`
   - For lower-level LIS/HIS/instrument connectivity channels
   - Functions: inbound JSON-RPC, inbound raw HL7/FHIR/REST, outbound ACK callback

### ไทย
ปัจจุบันระบบมี API 2 กลุ่ม และไม่ควรใช้ปนกัน:
1. `External Institution API`
   - สำหรับโรงพยาบาล หน่วยงาน และแพลตฟอร์มภายนอกที่เชื่อมกับ LIS
   - ใช้สร้างคำขอ ส่งไฟล์แนบคำขอ ตรวจสอบคำขอ/ผล ดาวน์โหลด PDF ดึง metadata และส่งผลแบบ REST/HL7
2. `Interface Channel API`
   - สำหรับช่องทางเชื่อมต่อระดับล่าง เช่น LIS/HIS/เครื่องมือ
   - ใช้รับข้อความแบบ JSON-RPC, Raw HL7/FHIR/REST และรับ ACK callback

## 2. Specification Files

- External Institution OpenAPI:
  - `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/openapi/external_api_v1.yaml`
- Interface Channel OpenAPI:
  - `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/openapi/interface_api_v1.yaml`
- Postman collection:
  - `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/postman/LIS_External_API.postman_collection.json`

## 3. Authentication

Configured per endpoint:
- `X-API-Key: <key>`
- `Authorization: Bearer <token>`
- `Authorization: Basic <base64(username:password)>`
- `auth_type = none`

Important:
- Current code **does allow** `auth_type = none`.
- This is acceptable for local testing only.
- Production recommendation remains: use `API Key` or `Bearer`.

## 4. External Institution API

Base path:
- `/lab/api/v1/{endpoint_code}`

### 4.1 Endpoint Matrix

| Method | Path | Purpose | Route type |
|---|---|---|---|
| POST | `/requests` | Create request | `json` |
| POST | `/requests/{request_no}/attachments` | Upload request attachments | `http` |
| GET | `/requests/{request_no}` | Query request | `http` |
| POST | `/results` | Push results by payload accession | `http` |
| POST | `/samples/{accession}/results` | Push results by path accession | `http` |
| GET | `/samples/{accession}/results` | Query sample results | `http` |
| POST | `/hl7/oru` | Push raw HL7 ORU | `http` |
| GET | `/samples/{accession}/report/pdf` | Download report PDF | `http` |
| GET | `/meta/sample_types` | Get specimen type metadata | `http` |
| GET | `/meta/services` | Get service metadata | `http` |
| GET | `/meta/profiles` | Get panel metadata | `http` |

### 4.2 Create Request

Route:
- `POST /lab/api/v1/{endpoint_code}/requests`

Request body:
- Top level:
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

Request line rules:
- `line_type` must be `service` or `profile`
- `service_code` required if `line_type = service`
- `profile_code` required if `line_type = profile`
- `specimen_sample_type` is required in current implementation
- `quantity` is accepted in payload but current portal/LIS flow normalizes request lines to one test occurrence per line in business logic

Current behavior:
- If `external_uid` already exists under the same endpoint, response is deduplicated.
- Patient and physician records are match-or-create under endpoint company scope.
- If required dynamic forms are missing, request is rejected.
- Attachments are validated before create and then stored on the request.

### 4.3 Upload Attachments To Existing Request

Route:
- `POST /lab/api/v1/{endpoint_code}/requests/{request_no}/attachments`

Supported payloads:
- `application/json`
  - `attachments: [{name, content_base64|datas, mimetype}]`
- `multipart/form-data`
  - repeated `files`

Constraints:
- each attachment max size: `10 MB`
- empty upload is rejected

### 4.4 Query Request

Route:
- `GET /lab/api/v1/{endpoint_code}/requests/{request_no}`

Returns:
- request header
- patient summary
- physician summary
- generated sample list
- request attachment summary list

### 4.5 Query Sample Results

Route:
- `GET /lab/api/v1/{endpoint_code}/samples/{accession}/results`

Returns:
- accession / barcode / state / report date
- patient summary
- request number
- analysis lines
- AI interpretation text if portal-visible

### 4.6 Push Results (REST)

Routes:
- `POST /lab/api/v1/{endpoint_code}/results`
- `POST /lab/api/v1/{endpoint_code}/samples/{accession}/results`

Payload core fields:
- `accession` or accession in path
- `results[]`
  - `service_code`
  - `result`
  - `note`
- optional `external_uid`
- optional `meta`

Current behavior:
- endpoint must allow result push
- endpoint direction must be `inbound` or `bidirectional`
- endpoint protocol must be `rest`
- API returns job-level ACK payload (`AA/AE/AR` semantics)

### 4.7 Push Results (HL7 ORU)

Route:
- `POST /lab/api/v1/{endpoint_code}/hl7/oru`

Requirements:
- endpoint protocol must be `hl7v2`
- endpoint must allow result push
- endpoint direction must be `inbound` or `bidirectional`

Body:
- raw HL7 ORU text

Response:
- raw HL7 ACK text
- ACK code may be `AA`, `AE`, or `AR`

### 4.8 Download PDF Report

Route:
- `GET /lab/api/v1/{endpoint_code}/samples/{accession}/report/pdf`

Behavior:
- returns binary PDF if sample state is `verified` or `reported`
- returns `409 report_not_ready` if report is not yet releasable

### 4.9 Metadata Endpoints

Routes:
- `GET /meta/sample_types`
- `GET /meta/services`
- `GET /meta/profiles`

Behavior:
- only active records in endpoint company scope
- metadata access must be enabled on endpoint

## 5. External API Error Codes

Observed in current implementation:
- `endpoint_not_found`
- `endpoint_protocol_not_allowed`
- `unauthorized`
- `request_push_disabled`
- `result_push_disabled`
- `result_query_disabled`
- `report_download_disabled`
- `metadata_query_disabled`
- `direction_not_allowed`
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
- `ingest_failed`
- `accession_required`
- `results_required`
- `request_not_found`
- `sample_not_found`
- `report_not_ready`
- `attachments_required`
- `invalid_attachment_payload`
- `attachment_name_or_data_missing`
- `attachment_decode_failed`
- `attachment_too_large`

## 6. Interface Channel API

Base path:
- `/lab/interface`

### 6.1 Endpoint Matrix

| Method | Path | Purpose | Route type |
|---|---|---|---|
| POST | `/inbound/{endpoint_code}` | Inbound JSON-RPC message | `jsonrpc` |
| POST | `/inbound/{endpoint_code}/raw` | Inbound raw HL7/FHIR/REST | `http` |
| POST | `/outbound/{endpoint_code}/ack` | Receive outbound ACK | `jsonrpc` |

### 6.2 Inbound JSON-RPC

Route:
- `POST /lab/interface/inbound/{endpoint_code}`

Input fields:
- `message_type`
- `payload`
- `external_uid`
- `raw_message`

Response fields:
- `ok`
- `ack_code`
- `job_id`
- `job_name`
- `state`
- `error`

### 6.3 Inbound Raw Message

Route:
- `POST /lab/interface/inbound/{endpoint_code}/raw`

Protocol behavior:
- `hl7v2`: parse HL7 and return HL7 ACK text
- `fhir`: parse FHIR resource and return FHIR `OperationOutcome`
- other protocol values: treat body as JSON object payload

### 6.4 Outbound ACK Callback

Route:
- `POST /lab/interface/outbound/{endpoint_code}/ack`

Input fields:
- `ack_code`
- `job_name`
- `job_id`
- `external_uid`
- `message`
- `payload`

## 7. Recommended Reading Order

1. `docs/openapi/external_api_v1.yaml`
2. `docs/openapi/interface_api_v1.yaml`
3. `docs/EXTERNAL_API_GUIDE_TRILINGUAL.md`

## 8. Integration Guidance For AI Agents

When generating client code, assume:
- external institution API and interface channel API are different products
- not all endpoints use the same Odoo route type
- binary PDF download is `http`, not JSON-RPC
- HL7 ORU returns plain text ACK, not JSON
- attachment upload supports both JSON base64 and multipart file upload
- some errors are business-rule errors from LIS, not transport errors
- endpoint capability flags can block otherwise valid calls
