# External / Interface API Guide (Chinese / English / Thai)

Scope note: portal website routes are excluded from this guide. This guide documents only machine-to-machine integration APIs.

## 1. What This Guide Covers | 本指南覆盖内容 | คู่มือนี้ครอบคลุมอะไร

### 中文
本文件同时说明两类接口：
- 外部机构业务接口 `External Institution API`
- LIS/HIS/仪器接口通道 `Interface Channel API`

### English
This guide covers two different integration layers:
- `External Institution API`
- `Interface Channel API`

### ไทย
คู่มือนี้อธิบาย 2 ชั้นของการเชื่อมต่อ:
- `External Institution API`
- `Interface Channel API`

## 2. When To Use Which API | 何时使用哪类API | ควรใช้ API แบบใดเมื่อไร

### 中文
如果你是医院、机构、预约平台、在线商城、表单系统，请优先用 `External Institution API`。
如果你是在做 HL7/FHIR、仪器结果回传、ACK 通道、HIS/LIS 双向消息，请用 `Interface Channel API`。

### English
Use `External Institution API` for hospital/institution ordering, portal-like request submission, marketplace integration, or form system integration.
Use `Interface Channel API` for HL7/FHIR messaging, analyzer/LIS connectivity, raw interface channels, and ACK callbacks.

### ไทย
ใช้ `External Institution API` เมื่อทำระบบสั่งตรวจจากโรงพยาบาล/หน่วยงาน/แพลตฟอร์มภายนอก
ใช้ `Interface Channel API` เมื่อทำ HL7/FHIR, เครื่องมือส่งผล, หรือช่องทาง ACK ระดับระบบ

## 3. Backend Setup | 后台配置 | การตั้งค่า Backend

### External Institution API
Path:
- `Laboratory > Configuration > Interface Endpoints`

Required setup:
1. `protocol = REST` for request/query/report/metadata APIs
2. `protocol = HL7 v2.x` only if using `/hl7/oru`
3. enable `Enable External Lab API`
4. set authentication
5. set `Data Company`
6. bind `External Institution` when data scope should be restricted
7. enable needed capability flags:
   - `Allow Request Push`
   - `Allow Result Push`
   - `Allow Result Query`
   - `Allow Report Download`
   - `Allow Metadata Query`

### Interface Channel API
Path:
- `Laboratory > Configuration > Interface Endpoints`

Required setup:
1. choose correct `protocol`: `REST`, `FHIR`, or `HL7 v2.x`
2. choose `direction`: `inbound`, `outbound`, or `bidirectional`
3. set authentication
4. configure mapping schema if HL7/FHIR parsing needs field mapping

## 4. External Institution API Flow | 外部机构API流程 | ลำดับการใช้งาน External API

### Recommended business flow
1. fetch metadata
2. create request
3. optionally upload request attachments
4. poll request and/or sample status
5. query sample results
6. download final PDF
7. optionally push external analyzer result back by REST or HL7 ORU

## 5. External Institution API Routes | 外部机构API路由 | เส้นทาง External API

Base:
- `/lab/api/v1/<endpoint_code>`

Routes:
1. `POST /requests`
2. `POST /requests/<request_no>/attachments`
3. `GET /requests/<request_no>`
4. `POST /results`
5. `POST /samples/<accession>/results`
6. `GET /samples/<accession>/results`
7. `POST /hl7/oru`
8. `GET /samples/<accession>/report/pdf`
9. `GET /meta/sample_types`
10. `GET /meta/services`
11. `GET /meta/profiles`

## 6. External Request Example | 外部申请示例 | ตัวอย่างสร้างคำขอ

```json
{
  "external_uid": "HIS-REQ-20260307-0001",
  "priority": "routine",
  "clinical_note": "STD panel",
  "preferred_template_code": "classic",
  "patient": {
    "name": "Patient A",
    "identifier": "ID-123456",
    "passport_no": "P12345678",
    "gender": "female",
    "birthdate": "1992-01-01",
    "phone": "13800000000",
    "email": "patient@example.com",
    "country_code": "TH",
    "state_code": "BKK",
    "city": "Bangkok",
    "informed_consent_signed": true
  },
  "physician": {
    "name": "Dr. Lee",
    "partner_ref": "DR-LEE-001",
    "license_no": "LIC-001",
    "specialty": "Infectious Disease",
    "department_code": "OPD",
    "institution_ref": "HOSP-001"
  },
  "lines": [
    {
      "line_type": "profile",
      "profile_code": "STD7-7",
      "specimen_ref": "SP1",
      "specimen_barcode": "CUP-0001",
      "specimen_sample_type": "swab",
      "note": "Primary sample"
    }
  ]
}
```

## 7. Attachment Upload Example | 附件上传示例 | ตัวอย่างอัปโหลดไฟล์แนบ

### JSON base64 mode
```json
{
  "attachments": [
    {
      "name": "request-form.jpg",
      "content_base64": "<base64>",
      "mimetype": "image/jpeg"
    }
  ]
}
```

### Multipart mode
- form field name: `files`
- repeat field for multiple files

## 8. Result Query / Result Push | 结果查询与回传 | ตรวจผลและส่งผลกลับ

### Query sample result
- `GET /lab/api/v1/<endpoint_code>/samples/<accession>/results`

### Push result by REST
```json
{
  "external_uid": "HIS-RES-20260307-0001",
  "accession": "ACC2602-00001",
  "results": [
    {"service_code": "STD_CT", "result": "7.2", "note": "Analyzer A1"}
  ]
}
```

### Push result by HL7 ORU
- `POST /lab/api/v1/<endpoint_code>/hl7/oru`
- body is raw HL7 text
- response is raw HL7 ACK

## 9. PDF Download | PDF下载 | ดาวน์โหลด PDF

- `GET /lab/api/v1/<endpoint_code>/samples/<accession>/report/pdf`

If report is not ready:
```json
{ "ok": false, "error": "report_not_ready" }
```

## 10. Metadata Sync | 元数据同步 | การซิงค์ Metadata

Recommended sequence:
1. sync `sample_types`
2. sync `services`
3. sync `profiles`
4. cache locally
5. refresh on schedule or before each shift

## 11. Interface Channel API Routes | 接口通道路由 | เส้นทาง Interface API

Base:
- `/lab/interface`

Routes:
1. `POST /inbound/<endpoint_code>`
2. `POST /inbound/<endpoint_code>/raw`
3. `POST /outbound/<endpoint_code>/ack`

### JSON-RPC inbound payload
```json
{
  "message_type": "order",
  "payload": {"external_uid": "ORDER-001"},
  "external_uid": "ORDER-001"
}
```

### Outbound ACK callback payload
```json
{
  "ack_code": "AA",
  "job_name": "OUT-0001",
  "job_id": 321,
  "external_uid": "ORDER-001",
  "message": "accepted",
  "payload": {}
}
```

## 12. Important Behavior Notes | 重要行为说明 | หมายเหตุสำคัญ

### 中文
- `auth_type = none` 当前实现允许，但不建议生产环境使用。
- `External Institution API` 中 `/requests` 是 Odoo `json` 路由；其余多数是 `http` 路由。
- `Interface Channel API` 中 `/inbound` 和 `/outbound/.../ack` 是 `jsonrpc` 路由。
- `/hl7/oru` 返回纯文本 ACK，不返回 JSON。
- 附件上传支持 JSON base64 和 multipart 两种模式。

### English
- `auth_type = none` is currently allowed by code, but not recommended for production.
- In `External Institution API`, `/requests` is an Odoo `json` route; most others are `http` routes.
- In `Interface Channel API`, `/inbound` and `/outbound/.../ack` are `jsonrpc` routes.
- `/hl7/oru` returns plain text ACK, not JSON.
- Attachment upload supports both JSON base64 and multipart modes.

### ไทย
- โค้ดปัจจุบันอนุญาต `auth_type = none` แต่ไม่แนะนำใน production
- ใน `External Institution API` เส้นทาง `/requests` เป็น `json` route ของ Odoo ส่วนใหญ่เส้นทางอื่นเป็น `http`
- ใน `Interface Channel API` เส้นทาง `/inbound` และ `/outbound/.../ack` เป็น `jsonrpc`
- `/hl7/oru` ตอบกลับเป็น ACK แบบข้อความล้วน ไม่ใช่ JSON
- การอัปโหลดไฟล์แนบรองรับทั้ง JSON base64 และ multipart

## 13. Source of Truth | 真实依据 | แหล่งอ้างอิงจริง

Implementation source files:
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/controllers/external_api.py`
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/controllers/interface_api.py`

Machine-readable specs:
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/openapi/external_api_v1.yaml`
- `/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/docs/openapi/interface_api_v1.yaml`
