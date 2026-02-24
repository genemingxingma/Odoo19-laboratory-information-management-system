# Development Guide (CN / EN / TH)

## CN - 开发维护指南

### 1) 适用范围
面向 Odoo 19 `laboratory_management` 的开发与维护人员。

### 2) 核心架构
- `models/lab_test_request.py`：申请单与生命周期
- `models/lab_sample.py`：样本流程与报告状态
- `models/lab_service.py` / `models/lab_profile.py`：检测目录
- `models/lab_patient.py` / `models/lab_physician.py`：实验室主数据
- `models/lab_dynamic_form.py`：动态表单
- `controllers/portal.py`：portal 入口
- `controllers/external_api.py`：外部机构接口

### 3) 最近关键能力
- 动态表单绑定 service/panel 并统一校验
- 申请附件支持 portal/内部/API 上传
- 患者/医生主数据与 `res.partner` 解耦

### 4) 开发流程
1. 修改代码
2. 升级模块
3. 验证菜单、申请、样本、报告、AI流程

升级命令示例：
```bash
python <odoo-bin> -c <conf> -d <db> -u laboratory_management --stop-after-init
```

### 5) 编码与i18n规范
- 代码源语言统一英文
- 通过翻译文件提供中文和泰文
- 业务规则尽量数据驱动，避免硬编码

---

## EN - Development Guide

### 1) Scope
For developers maintaining `laboratory_management` on Odoo 19.

### 2) Core architecture
- `models/lab_test_request.py`: request lifecycle and business rules
- `models/lab_sample.py`: accession, analysis, and report release states
- `models/lab_service.py` / `models/lab_profile.py`: catalog and panels
- `models/lab_patient.py` / `models/lab_physician.py`: lab-native master data
- `models/lab_dynamic_form.py`: dynamic form engine
- `controllers/portal.py`: portal flows
- `controllers/external_api.py`: institution API endpoints

### 3) Current baseline capabilities
- Dynamic forms bound to services/panels with unified validation
- Request attachments in portal/backoffice/API
- Patient and physician models decoupled from plain partner usage

### 4) Standard dev workflow
1. Update code
2. Upgrade module
3. Verify menu loading, request flow, sample flow, report (H5/PDF), AI interpretation

Upgrade command:
```bash
python <odoo-bin> -c <conf> -d <db> -u laboratory_management --stop-after-init
```

### 5) Coding and i18n rules
- Source code language: English
- Translation support: Chinese and Thai
- Keep logic data-driven; avoid hard-coded business catalogs

---

## TH - คู่มือนักพัฒนา

### 1) ขอบเขต
สำหรับนักพัฒนาที่ดูแล `laboratory_management` บน Odoo 19

### 2) โครงสร้างหลัก
- `models/lab_test_request.py`: วงจรคำขอ
- `models/lab_sample.py`: วงจรตัวอย่างและการปล่อยรายงาน
- `models/lab_service.py` / `models/lab_profile.py`: รายการตรวจและแพ็กเกจ
- `models/lab_patient.py` / `models/lab_physician.py`: ข้อมูลหลักของห้องปฏิบัติการ
- `models/lab_dynamic_form.py`: แบบฟอร์มแบบไดนามิก
- `controllers/portal.py`: ขั้นตอนในพอร์ทัล
- `controllers/external_api.py`: API ภายนอก

### 3) ความสามารถหลักล่าสุด
- dynamic form ผูกกับ service/panel และตรวจสอบครบก่อนส่ง
- รองรับไฟล์แนบใน portal/backoffice/API
- แยกโมเดลผู้ป่วย/แพทย์จาก `res.partner` แบบเดิม

### 4) ขั้นตอนพัฒนา
1. แก้โค้ด
2. อัปเกรดโมดูล
3. ทดสอบเมนู คำขอ ตัวอย่าง รายงาน (H5/PDF) และ AI interpretation

คำสั่งอัปเกรด:
```bash
python <odoo-bin> -c <conf> -d <db> -u laboratory_management --stop-after-init
```

### 5) กฎการเขียนโค้ดและ i18n
- ภาษาโค้ดหลักเป็นภาษาอังกฤษ
- รองรับคำแปลภาษาจีนและภาษาไทย
- ใช้แนวทาง data-driven และหลีกเลี่ยง hard-coded business logic
