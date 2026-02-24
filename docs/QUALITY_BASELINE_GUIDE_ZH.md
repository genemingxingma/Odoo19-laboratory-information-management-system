# Quality Baseline Guide (CN / EN / TH)

## CN - 质量基线配置指南

对应脚本：`scripts/setup_quality_baseline_local.py`

### 1) 执行
```bash
/Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
/Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
-c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
< /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_quality_baseline_local.py
```

### 2) 基线包含
- QC Materials + Westgard规则
- QC Runs + Daily Snapshots
- QC Trend Profile + Snapshot
- Quality Program + Internal Audit + Training + KPI
- EQA Scheme + Round + Closure Report
- Compliance Snapshot + Compliance Audit Report
- Method Validation（批准状态）

### 3) 关键参数
- `target_value/std_dev`: 质控中心值与波动
- `rule_ids`: Westgard触发规则
- `warning_sigma/reject_sigma`: 趋势告警阈值
- `tolerance` (EQA): 通过/失败容差
- `overall_pass/effective_*`: 方法学验证是否允许放行

---

## EN - Quality Baseline Guide

Script: `scripts/setup_quality_baseline_local.py`

### 1) Run
```bash
/Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
/Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
-c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
< /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_quality_baseline_local.py
```

### 2) What baseline is created
- QC materials and Westgard rule assignments
- QC runs and daily snapshots
- QC trend profile and published snapshot
- Quality program, internal audit, training, KPI snapshot
- EQA schemes, rounds, and closure report
- Compliance snapshot and compliance audit report
- Approved method validation records

### 3) Core parameter meaning
- `target_value/std_dev`: QC center and dispersion
- `rule_ids`: rejection/warning logic
- `warning_sigma/reject_sigma`: trend thresholds
- `tolerance` in EQA: pass/fail boundary
- `overall_pass/effective_*`: release eligibility window

---

## TH - คู่มือค่าพื้นฐานด้านคุณภาพ

สคริปต์: `scripts/setup_quality_baseline_local.py`

### 1) วิธีรัน
```bash
/Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
/Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
-c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
< /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_quality_baseline_local.py
```

### 2) สิ่งที่ตั้งค่าให้
- QC material และกฎ Westgard
- QC run และ daily snapshot
- QC trend profile และ snapshot
- Quality program, internal audit, training, KPI
- EQA scheme/round/closure report
- Compliance snapshot และ compliance audit report
- Method validation ที่อนุมัติแล้ว

### 3) ความหมายพารามิเตอร์หลัก
- `target_value/std_dev`: ค่าเป้าหมายและการกระจายของ QC
- `rule_ids`: กฎเตือน/ปฏิเสธ
- `warning_sigma/reject_sigma`: เกณฑ์แนวโน้ม
- `tolerance` (EQA): ขอบเขตผ่าน/ไม่ผ่าน
- `overall_pass/effective_*`: เงื่อนไขอนุญาตปล่อยผล
