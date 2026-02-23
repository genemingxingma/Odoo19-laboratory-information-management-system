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
2. `GET /requests/<request_no>`
3. `GET /samples/<accession>/results`
4. `GET /samples/<accession>/report/pdf`
5. `GET /meta/sample_types`
6. `GET /meta/services`
7. `GET /meta/profiles`

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
    "gender": "female",
    "birthdate": "1992-01-01",
    "phone": "13800000000"
  },
  "physician": {
    "name": "Dr. Lee",
    "partner_ref": "DR-LEE-001"
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

---

## 5. Result Query Example | 结果查询示例 | ตัวอย่างตรวจผล

Request:
- `GET /lab/api/v1/<endpoint_code>/samples/ACC2602-00001/results`

Response includes:
- sample state
- analysis lines (`service_code`, `result_value`, `binary_interpretation`)
- approved AI interpretation text (if visible)

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
