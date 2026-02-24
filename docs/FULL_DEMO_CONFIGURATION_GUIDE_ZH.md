# LIS Full Demo Configuration Guide (CN / EN / TH)

## CN - 全量演示配置指南

对应脚本：`scripts/setup_full_demo_local.py`

### 1) 一键执行
```bash
/Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
/Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
-c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
< /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_full_demo_local.py
```

### 2) 配置内容
- 主数据：标本类型、结果单位
- 机构与医生：Demo Medical Center、Gynecology/Pathology
- Portal账号：个人与机构两类
- Service目录：生化、HPV14、STD7、病理
- Panel：HPV14、STD3/4/6/7、Pathology
- 解释规则：HPV14/STD7 interpretation profiles
- 动态表单：STD 风险与知情同意
- 试剂盒和批号：多重PCR覆盖关系
- 报告模板：机构默认模板绑定 + AI提示词
- Request Type范围：individual/institution可见目录

### 3) 自动生成演示流程
- STD7单例全流程（申请到报告）
- HPV 96孔板分配 + worksheet
- 病理病例流程（gross/micro/final diagnosis）

### 4) 参数作用速查
- `result_type`: 决定结果录入形态（numeric/text）
- `auto_binary_*`: 数值自动映射阳性/阴性
- `require_reagent_lot`: 强制批号追溯
- `turnaround_hours`: 预计时效与逾期管理
- `institution default template`: 机构默认报告模板
- `dynamic form required`: 提交前强制补全字段

---

## EN - Full Demo Configuration Guide

Script: `scripts/setup_full_demo_local.py`

### 1) Run in one command
```bash
/Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
/Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
-c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
< /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_full_demo_local.py
```

### 2) What gets configured
- Master data: specimen types and result units
- Institution and physicians: Demo Medical Center with departments
- Portal users: individual + institution
- Service catalog: chemistry, HPV14, STD7, pathology
- Panels: HPV14, STD3/4/6/7, pathology
- Interpretation profiles for HPV/STD
- Dynamic form for STD risk/consent
- Assay kits and reagent lots for multiplex workflows
- Report templates with institution default + AI prompt
- Request type catalog scope for individual vs institution

### 3) Auto-generated demo flows
- End-to-end STD7 request/sample/report flow
- HPV 96-well plate assignment + worksheet flow
- Pathology case flow (gross/micro/final diagnosis)

### 4) Parameter meaning
- `result_type`: numeric or text result handling
- `auto_binary_*`: auto positive/negative classification
- `require_reagent_lot`: mandatory lot traceability
- `turnaround_hours`: expected SLA and overdue logic
- `institution default template`: organization-level report style
- `dynamic form required`: enforced required fields before submit

---

## TH - คู่มือการตั้งค่าเดโมแบบครบถ้วน

สคริปต์: `scripts/setup_full_demo_local.py`

### 1) คำสั่งรันครั้งเดียว
```bash
/Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
/Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
-c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
< /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_full_demo_local.py
```

### 2) สิ่งที่ระบบจะตั้งค่าให้
- ข้อมูลหลัก: ประเภทสิ่งส่งตรวจและหน่วยผลตรวจ
- สถาบันและแพทย์: Demo Medical Center และแผนก
- ผู้ใช้พอร์ทัล: บุคคลทั่วไป + องค์กร
- รายการตรวจ: เคมีคลินิก, HPV14, STD7, พยาธิวิทยา
- แพ็กเกจการตรวจ (Panels)
- โปรไฟล์การแปลผล HPV/STD
- แบบฟอร์มเสริมสำหรับ STD (ความเสี่ยง/ยินยอม)
- ชุดน้ำยาและล็อตสำหรับ multiplex PCR
- เทมเพลตรายงานเริ่มต้นตามองค์กร + AI prompt
- การจำกัดแคตตาล็อกตามประเภทคำขอ

### 3) โฟลว์เดโมที่สร้างอัตโนมัติ
- โฟลว์ STD7 ครบตั้งแต่คำขอถึงรายงาน
- โฟลว์แผ่น 96 หลุมสำหรับ HPV + worksheet
- โฟลว์พยาธิวิทยา (gross/micro/final diagnosis)

### 4) ความหมายของพารามิเตอร์หลัก
- `result_type`: รูปแบบการบันทึกผล (ตัวเลข/ข้อความ)
- `auto_binary_*`: แปลงผลเป็นบวก/ลบอัตโนมัติ
- `require_reagent_lot`: บังคับติดตามล็อตน้ำยา
- `turnaround_hours`: SLA และการตรวจงานล่าช้า
- `institution default template`: รูปแบบรายงานมาตรฐานขององค์กร
- `dynamic form required`: บังคับกรอกข้อมูลก่อนส่งคำขอ
