# External API Guide (Chinese / English / Thai)

## 1. Scope | 范围 | ขอบเขต

### 中文
外部医院/机构可通过 API：
- 推送检验申请
- 查询申请与样本结果
- 下载 PDF 报告

### English
External hospitals/institutions can use API to:
- Push lab test requests
- Query request/sample results
- Download PDF reports

### ไทย
โรงพยาบาล/หน่วยงานภายนอกสามารถใช้ API เพื่อ:
- ส่งคำขอตรวจ
- ตรวจสอบผลคำขอและผลตัวอย่าง
- ดาวน์โหลดรายงาน PDF

---

## 2. Endpoint Setup | 接口端点配置 | การตั้งค่า Endpoint

### 中文
路径：`Laboratory > Configuration > Interface Endpoints`
1. 新建 endpoint（`protocol=REST`）
2. 设置鉴权（建议 `API Key` 或 `Bearer`）
3. 勾选 `Enable External Lab API`
4. 绑定 `External Institution` 与 `Data Company`
5. 勾选能力：
   - `Allow Request Push`
   - `Allow Result Query`
   - `Allow Report Download`
   - `Allow Metadata Query`

### English
Path: `Laboratory > Configuration > Interface Endpoints`
1. Create endpoint (`protocol=REST`)
2. Set authentication (`API Key` or `Bearer` recommended)
3. Enable `Enable External Lab API`
4. Bind `External Institution` and `Data Company`
5. Enable capabilities:
   - `Allow Request Push`
   - `Allow Result Query`
   - `Allow Report Download`
   - `Allow Metadata Query`

### ไทย
เมนู: `Laboratory > Configuration > Interface Endpoints`
1. สร้าง endpoint (`protocol=REST`)
2. ตั้งค่าการยืนยันตัวตน (แนะนำ `API Key` หรือ `Bearer`)
3. เปิด `Enable External Lab API`
4. ผูก `External Institution` และ `Data Company`
5. เปิดสิทธิ์:
   - `Allow Request Push`
   - `Allow Result Query`
   - `Allow Report Download`
   - `Allow Metadata Query`

---

## 3. API Endpoints | API地址 | เส้นทาง API

Base: `/lab/api/v1/<endpoint_code>`

1. `POST /requests`
2. `POST /results` (REST result push)
3. `POST /samples/<accession>/results` (REST result push by accession path)
4. `POST /hl7/oru` (HL7 ORU raw text push)
5. `GET /requests/<request_no>`
6. `GET /samples/<accession>/results`
7. `GET /samples/<accession>/report/pdf`
8. `GET /meta/sample_types`
9. `GET /meta/services`
10. `GET /meta/profiles`

Auth header examples:
- `X-API-Key: <api_key>`
- `Authorization: Bearer <token>`

---

## 4. Request Push Example | 申请推送示例 | ตัวอย่างส่งคำขอ

```json
{
  "external_uid": "HIS-REQ-20260222-0001",
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
    "emergency_contact_name": "Family A",
    "emergency_contact_phone": "13800009999",
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
      "quantity": 1,
      "specimen_ref": "SP1",
      "specimen_barcode": "CUP-0001",
      "specimen_sample_type": "swab",
      "note": "Primary sample"
    }
  ]
}
```

Response:
```json
{
  "ok": true,
  "request": {
    "request_no": "REQ2602-00001",
    "state": "submitted"
  }
}
```

Notes:
- `external_uid` is idempotent key per endpoint.
- Re-push with same `external_uid` returns existing request (`deduplicated=true`).
- Specimen type should be passed by each line via `specimen_sample_type`.
- If target service/panel requires dynamic forms, pass `dynamic_forms` in request payload.
- API will match-or-create `lab.patient` / `lab.physician` using supplied identity fields under endpoint `Data Company`.

Patient matching priority:
1. `patient.id`
2. `patient.identifier` / `patient_id_no` / `id_no`
3. `patient.passport_no`
4. `patient.name + patient.phone`

Physician matching priority:
1. `physician.id`
2. `physician.code` / `partner_ref`
3. `physician.license_no`
4. `physician.name + physician.phone`

Dynamic form payload example:
```json
{
  "dynamic_forms": [
    {
      "form_code": "STD_PRETEST_QA",
      "answers": {
        "recent_exposure": "yes",
        "symptoms": "no",
        "consent": true
      }
    }
  ]
}
```

---

## 5. Result Query Example | 结果查询示例 | ตัวอย่างตรวจผล

Request:
- `GET /lab/api/v1/<endpoint_code>/samples/ACC2602-00001/results`

Response includes:
- sample state
- analysis lines (`service_code`, `result_value`, `binary_interpretation`)
- approved AI interpretation text (if visible)
- structured patient info (`id`, `name`, `identifier`, `passport_no`)

---

## 5.1 Result Push Example | 结果回传示例 | ตัวอย่างส่งผลตรวจกลับ

REST JSON:
```json
{
  "external_uid": "HIS-RES-20260226-0001",
  "accession": "ACC2602-00001",
  "results": [
    {"service_code": "STD_CT", "result": "7.2", "note": "Analyzer A1"}
  ]
}
```

HL7 ORU endpoint:
- `POST /lab/api/v1/<endpoint_code>/hl7/oru`
- Body is raw HL7 ORU message text
- Returns HL7 ACK (`AA/AE/AR`)

---

## 6. PDF Download | PDF下载 | ดาวน์โหลด PDF

Request:
- `GET /lab/api/v1/<endpoint_code>/samples/ACC2602-00001/report/pdf`

Return:
- `Content-Type: application/pdf`
- attachment file

If report not ready:
- HTTP 409 + JSON `{ "ok": false, "error": "report_not_ready" }`

---

## 7. Data Isolation and Security | 数据隔离与安全 | การแยกข้อมูลและความปลอดภัย

### 中文
- 所有 API 查询默认限定 `Data Company`
- 且限定在 `External Institution` 的可见范围内
- 禁止使用 `auth_type = none`

### English
- All API data is scoped by `Data Company`
- Further filtered by `External Institution` visibility domain
- `auth_type = none` is blocked for external API endpoints

### ไทย
- ข้อมูล API ถูกจำกัดด้วย `Data Company`
- และกรองตามขอบเขตการมองเห็นของ `External Institution`
- ไม่อนุญาต `auth_type = none` สำหรับ endpoint ภายนอก

---

## 8. Metadata Sync Recommendation | 元数据同步建议 | คำแนะนำการซิงค์ Metadata

### 中文
- 对接系统应先拉取 `sample_types/services/profiles`，再给用户展示可选项。
- 建议定时刷新 metadata（例如每天或每次班次开始）。
- 若返回 `metadata_query_disabled`，请联系管理员在 endpoint 上开启 `Allow Metadata Query`。

### English
- External clients should fetch `sample_types/services/profiles` before showing selectable options.
- Refresh metadata regularly (for example, daily or at shift start).
- If API returns `metadata_query_disabled`, ask LIS admin to enable `Allow Metadata Query` on endpoint.

### ไทย
- ระบบภายนอกควรดึง `sample_types/services/profiles` ก่อนแสดงตัวเลือกให้ผู้ใช้
- ควรรีเฟรช metadata เป็นระยะ (เช่น ทุกวัน หรือก่อนเริ่มกะ)
- หาก API ตอบกลับ `metadata_query_disabled` ให้ผู้ดูแล LIS เปิด `Allow Metadata Query` ที่ endpoint

---

## 9. Metadata Response Examples | 元数据响应示例 | ตัวอย่างผลลัพธ์ Metadata

### Sample Types
`GET /lab/api/v1/<endpoint_code>/meta/sample_types`

```json
{
  "ok": true,
  "sample_types": [
    {"code": "swab", "name": "Swab", "is_default": true},
    {"code": "blood", "name": "Whole Blood", "is_default": false}
  ]
}
```

### Services
`GET /lab/api/v1/<endpoint_code>/meta/services`

```json
{
  "ok": true,
  "services": [
    {"code": "STD_CT", "name": "Chlamydia Trachomatis PCR", "sample_type": "swab"}
  ]
}
```

### Profiles
`GET /lab/api/v1/<endpoint_code>/meta/profiles`

```json
{
  "ok": true,
  "profiles": [
    {"code": "STD7-7", "name": "STD 7 Panel", "sample_type": "swab"}
  ]
}
```
