# 质量菜单基线配置指南（QC/EQA/合规）

对应脚本：
`/Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_quality_baseline_local.py`

## 1. 执行方式

```bash
/Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
/Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
-c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
< /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_quality_baseline_local.py
```

## 2. 为什么“质量菜单”以前看起来很多是空的

质量菜单中的多数对象属于“策略/规则/统计”层，不是交易层。系统不会默认写死阈值和方案，否则会误导真实实验室。  
需要先配置以下对象，菜单才会“有内容且有意义”：

- QC 材料（目标值、SD、Westgard 规则）
- QC 运行数据（用于趋势/告警）
- EQA 方案与轮次（用于室间质评）
- 年度质量计划/审核/培训/KPI
- 合规快照与审计报表
- 方法学验证

## 3. 脚本写入了哪些基线

### 3.1 QC（室内质控）
- 3个 QC 材料：
  - `QC-GLU-L1`
  - `QC-ALT-L1`
  - `QC-STD-CT`
- 规则：
  - 生化使用 `13s/22s/R4s/41s/10x`
  - 分子使用 `13s/12s/22s`
- 自动生成近期 QC runs（包含 warning/reject 示例）
- 自动抓取 QC Daily Snapshot

参数意义：
- `target_value`：方法目标值
- `std_dev`：方法波动（控制 z-score）
- `rule_ids`：Westgard 告警/拒绝逻辑

### 3.2 QC 趋势
- 趋势模板：`BASELINE-CORE`
- 关键参数：
  - `window_size=20`
  - `warning_sigma=2.0`
  - `reject_sigma=3.0`
- 自动生成并发布一个趋势快照

### 3.3 质量计划 / 审核 / 培训 / KPI
- 创建并激活当年 Quality Program
- 自动生成默认计划条目
- 创建并闭环一个 Internal Audit（含 finding）
- 创建并完成一个 Training Session（含 attendee）
- 自动抓取 KPI Snapshot

### 3.4 EQA（室间质评）
- 方案：
  - `EQA-CHEM-CORE`
  - `EQA-MICRO-MPX`
- 每个方案创建 1 个轮次，录入结果并完成 submit/evaluate/close
- 自动生成 EQA Closure Report 并 publish

参数意义：
- `tolerance`：判定 pass/fail 的容差边界
- `pass_rate`：方案或周期层面的通过率

### 3.5 合规报表
- 生成并发布 `Compliance Snapshot`
- 生成并批准 `Compliance Audit Report`（微生物）

### 3.6 方法学验证
- 创建并批准 2 个方法验证：
  - `GLU-V1.0`
  - `STD-CT-V1.0`
- 设置计划、结果、验收标准、有效期、复审周期

参数意义：
- `overall_pass`：是否允许进入批准流程
- `effective_from/effective_to`：放行有效窗口
- `review_interval_months`：复审节奏

## 4. 推荐学习路径

1. `Quality > QC Materials / QC Runs / QC Daily Snapshots`
2. `Quality > QC Trend Profiles / QC Trend Snapshots`
3. `Quality > Quality Programs / Internal Audits / Training Sessions / KPI Snapshots`
4. `Quality > EQA Schemes / EQA Rounds / EQA Closure Reports`
5. `Quality > Compliance Reports / Compliance Audit Reports`
6. `Quality > Method Validation`

## 5. 你接下来要按真实实验室调整的参数

- QC 目标值和 SD（按仪器/试剂/方法学）
- Westgard 规则组合（按科室风险偏好）
- EQA 容差与评价逻辑（按外部提供者要求）
- 质量计划条目和 KPI 目标值（按管理目标）
- 方法学验证验收标准（按 ISO15189 与本地法规）
