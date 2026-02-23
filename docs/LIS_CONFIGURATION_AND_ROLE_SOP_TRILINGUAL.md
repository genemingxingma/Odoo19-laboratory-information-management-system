# LIS Configuration and Role SOP (Chinese / English / Thai)

## 0. Document Scope | 文档范围 | ขอบเขตเอกสาร

### 中文
本文档用于 `laboratory_management` 模块的标准部署与运营，覆盖：
- 系统初始化配置
- 主数据配置（标本类型、服务、组合、报告模板、AI）
- Portal（个人/机构）使用配置
- 角色权限与端到端操作流程

### English
This document defines standard deployment and operation for `laboratory_management`, including:
- Initial system configuration
- Master data setup (sample types, services, profiles, report templates, AI)
- Portal setup for individual and institutional users
- Role-based permissions and end-to-end workflows

### ไทย
เอกสารนี้กำหนดแนวทางติดตั้งและใช้งานมาตรฐานของโมดูล `laboratory_management` ครอบคลุม:
- การตั้งค่าเริ่มต้นระบบ
- การตั้งค่า Master Data (ชนิดสิ่งส่งตรวจ, บริการ, โปรไฟล์, แม่แบบรายงาน, AI)
- การตั้งค่า Portal สำหรับลูกค้าบุคคลและลูกค้าองค์กร
- สิทธิ์ตามบทบาทและขั้นตอนการทำงานแบบ end-to-end

---

## 1. Pre-Deployment Checklist | 上线前检查清单 | เช็กลิสต์ก่อนใช้งานจริง

### 中文
1. Odoo 19 CE/EE 可用，数据库已创建。
2. 安装模块依赖：`mail` `portal` `website` `account` `sale` `website_sale` `base_setup`。
3. 多公司结构已确定（若启用多公司隔离）。
4. 已准备报告模板、检测项目目录、标本类型与医生/机构名单。
5. 若启用 AI：准备 OpenAI / OpenAI-Compatible / Ollama 参数。

### English
1. Odoo 19 CE/EE is running and target database is created.
2. Required dependencies are installed: `mail`, `portal`, `website`, `account`, `sale`, `website_sale`, `base_setup`.
3. Multi-company structure is defined (if isolation is required).
4. Report templates, service catalog, sample types, physician and institution list are prepared.
5. For AI features, provider credentials/endpoints are prepared.

### ไทย
1. ระบบ Odoo 19 CE/EE พร้อมใช้งานและมีฐานข้อมูลปลายทางแล้ว
2. ติดตั้งโมดูลที่ต้องพึ่งพา: `mail`, `portal`, `website`, `account`, `sale`, `website_sale`, `base_setup`
3. กำหนดโครงสร้างหลายบริษัทแล้ว (หากต้องการแยกข้อมูล)
4. เตรียมแม่แบบรายงาน, รายการบริการตรวจ, ชนิดสิ่งส่งตรวจ, รายชื่อแพทย์/หน่วยงาน
5. หากใช้ AI ให้เตรียมค่า provider/endpoint/key

---

## 2. Initial Configuration | 初始配置步骤 | ขั้นตอนตั้งค่าเริ่มต้น

### 2.1 Install and basic parameters | 安装与基础参数 | ติดตั้งและค่าพื้นฐาน

#### 中文
1. 应用中安装 `Laboratory Management`。
2. 进入 `Laboratory > Configuration > AI Settings`：
   - 选择 `AI Provider`。
   - 配置模型与URL。
   - 建议启用：
     - `Generate AI Asynchronously on Report Release`
     - `Cache Report PDF on Release`
     - `AI Queue Batch Size = 50`（按服务器能力调整）
3. 检查定时任务（技术菜单）启用：
   - `Lab: Process AI Interpretation Queue`
   - `Lab: Retry AI Interpretation Errors`

#### English
1. Install `Laboratory Management` from Apps.
2. Go to `Laboratory > Configuration > AI Settings`:
   - Select `AI Provider`.
   - Configure model and endpoint.
   - Recommended enabled options:
     - `Generate AI Asynchronously on Report Release`
     - `Cache Report PDF on Release`
     - `AI Queue Batch Size = 50` (tune by server capacity)
3. Verify scheduled actions are active:
   - `Lab: Process AI Interpretation Queue`
   - `Lab: Retry AI Interpretation Errors`

#### ไทย
1. ติดตั้ง `Laboratory Management` จากเมนู Apps
2. ไปที่ `Laboratory > Configuration > AI Settings`:
   - เลือก `AI Provider`
   - ตั้งค่าโมเดลและ URL
   - แนะนำให้เปิด:
     - `Generate AI Asynchronously on Report Release`
     - `Cache Report PDF on Release`
     - `AI Queue Batch Size = 50` (ปรับตามทรัพยากรเซิร์ฟเวอร์)
3. ตรวจสอบ Scheduled Action ให้ active:
   - `Lab: Process AI Interpretation Queue`
   - `Lab: Retry AI Interpretation Errors`

### 2.2 Master data | 主数据配置 | ตั้งค่า Master Data

#### 中文
1. `Laboratory > Configuration > Master Data > Sample Types`：维护中英泰标本类型。
2. `Laboratory > Configuration > Physicians`：创建医生并关联机构/科室。
3. `Laboratory > Configuration > Services`：建立检测服务（方法、单位、参考区间、TAT、自动判读阈值）。
4. `Laboratory > Configuration > Profiles`：将多个服务组合为套餐。
5. `Laboratory > Configuration > Report Templates`：
   - 选择模板类型（classic/clinical/compact）
   - 配置 AI 提示词模板（可引用报告内容变量）

#### English
1. `Laboratory > Configuration > Master Data > Sample Types`: maintain sample types with CN/EN/TH labels.
2. `Laboratory > Configuration > Physicians`: create physicians and map institution/department.
3. `Laboratory > Configuration > Services`: define tests (method, unit, reference range, TAT, auto interpretation cutoff).
4. `Laboratory > Configuration > Profiles`: group services into packages.
5. `Laboratory > Configuration > Report Templates`:
   - Select template type (classic/clinical/compact)
   - Configure AI prompt templates with report variables

#### ไทย
1. `Laboratory > Configuration > Master Data > Sample Types`: ตั้งชื่อชนิดสิ่งส่งตรวจแบบจีน/อังกฤษ/ไทย
2. `Laboratory > Configuration > Physicians`: สร้างแพทย์และผูกกับหน่วยงาน/แผนก
3. `Laboratory > Configuration > Services`: กำหนดบริการตรวจ (วิธี, หน่วย, ช่วงอ้างอิง, TAT, เกณฑ์แปลผลอัตโนมัติ)
4. `Laboratory > Configuration > Profiles`: จัดบริการหลายรายการเป็นแพ็กเกจ
5. `Laboratory > Configuration > Report Templates`:
   - เลือกชนิดเทมเพลต (classic/clinical/compact)
   - ตั้งค่า Prompt สำหรับ AI โดยอ้างอิงตัวแปรในรายงาน

### 2.3 Portal and customer setup | Portal与客户配置 | ตั้งค่า Portal และลูกค้า

#### 中文
1. 联系人启用 Portal 用户。
2. 机构客户：
   - 公司联系人设为公司
   - 医生由实验室后台创建并绑定该机构
3. 个人客户：联系人直接作为 requester/patient。
4. 在 `Laboratory > Configuration > Permissions` 或用户组中分配：
   - 可提交申请（Request）
   - 可查看报告（Report）

#### English
1. Enable portal access for contacts.
2. Institutional customers:
   - Use company contact as commercial entity
   - Create physicians in backend and map them to institution
3. Individual customers: contact can be requester/patient directly.
4. Assign portal capabilities via permissions/groups:
   - Request submission
   - Report access

#### ไทย
1. เปิดสิทธิ์ Portal ให้ผู้ติดต่อ
2. ลูกค้าองค์กร:
   - ตั้งผู้ติดต่อแบบบริษัทเป็น entity หลัก
   - สร้างแพทย์จากหลังบ้านและผูกกับหน่วยงาน
3. ลูกค้าบุคคล: ใช้ผู้ติดต่อเป็นผู้ส่งตรวจ/ผู้ป่วยได้โดยตรง
4. กำหนดสิทธิ์ผ่านกลุ่ม/permission:
   - ส่งคำขอตรวจ
   - ดูรายงาน

---

## 3. Recommended Service Configuration Example | 检测服务配置示例 | ตัวอย่างการตั้งค่าบริการ

### 中文
HPV/多重PCR建议：
1. 每个亚型建单独 service（结果值 Ct）。
2. 组合逻辑使用 profile（3项/4项/6项/7项）。
3. 自动判读规则（示例）：`Ct >= 33 阴性`，`Ct < 33 阳性`。
4. 最终总解释通过 `Interpretation Profile` 或 `Report Template + AI` 输出。

### English
Recommended HPV/multiplex PCR setup:
1. Build one service per target (Ct numeric result).
2. Use profiles for package composition (3/4/6/7 panel).
3. Auto interpretation sample rule: `Ct >= 33 Negative`, `Ct < 33 Positive`.
4. Final panel interpretation via `Interpretation Profile` or `Report Template + AI`.

### ไทย
แนวทางตั้งค่า HPV/Multiplex PCR:
1. สร้างบริการแยกตามเป้าหมาย (ผล Ct แบบตัวเลข)
2. ใช้ Profile สำหรับแพ็กเกจ 3/4/6/7 รายการ
3. กฎแปลผลอัตโนมัติ: `Ct >= 33 = Negative`, `Ct < 33 = Positive`
4. สรุปผลสุดท้ายใช้ `Interpretation Profile` หรือ `Report Template + AI`

---

## 4. Role Matrix | 角色矩阵 | ตารางบทบาท

| Role | Key Responsibility |
|---|---|
| Lab Manager | Governance, approval policy, release authority, KPI/compliance |
| Reception/Accession | Intake, patient/request validation, sample receiving |
| Technician/Analyst | Test execution and raw result entry |
| QC Reviewer | QC run review, rule handling, release gate control |
| Medical Reviewer | Clinical review, final interpretation approval |
| Billing/Finance | Quote, invoice, payment and reconciliation |
| Portal User (Individual) | Submit request, track sample, view/download report |
| Portal User (Institution) | Batch request, doctor-linked ordering, report follow-up |

---

## 5. End-to-End Workflow by Role | 分角色操作流程 | ขั้นตอนการทำงานตามบทบาท

### 5.1 Reception / Accession | 采样受理 | รับสิ่งส่งตรวจ

#### 中文
1. 新建 `Test Request`，选择客户类型（个人/机构）。
2. 填写患者信息（可通过证件号回填历史信息）。
3. 添加标本-项目组合（支持多个组合/多个标本）。
4. 提交申请 -> 分诊 -> 报价（如启用计费）。
5. 审批后执行 `Create Samples` 生成 accession。
6. 采样收样后执行 `Receive`。

#### English
1. Create `Test Request` with customer type (individual/institution).
2. Fill patient data (history lookup by ID if configured).
3. Add specimen-service combinations (multi-combo/multi-specimen supported).
4. Submit -> triage -> quote (if billing enabled).
5. After approval, run `Create Samples`.
6. On physical receipt, run `Receive`.

#### ไทย
1. สร้าง `Test Request` เลือกลูกค้าแบบบุคคล/องค์กร
2. กรอกข้อมูลผู้ป่วย (ค้นย้อนหลังด้วยเลขเอกสารได้)
3. เพิ่มชุดสิ่งส่งตรวจ-บริการ (รองรับหลายชุด/หลายตัวอย่าง)
4. Submit -> Triage -> Quote (ถ้าเปิด billing)
5. เมื่ออนุมัติแล้วกด `Create Samples`
6. เมื่อรับตัวอย่างจริงให้กด `Receive`

### 5.2 Technician / Analyst | 技师检测 | นักเทคนิค

#### 中文
1. 进入样本，执行 `Start`。
2. 填写各分析项结果并标记完成。
3. 所有项目完成后执行 `Mark to Verify`。

#### English
1. Open sample and run `Start`.
2. Enter analysis results and mark each line done.
3. When all lines are done, run `Mark to Verify`.

#### ไทย
1. เปิดตัวอย่างและกด `Start`
2. กรอกผลวิเคราะห์และทำเครื่องหมายเสร็จในแต่ละรายการ
3. เมื่อครบทุกรายการให้กด `Mark to Verify`

### 5.3 QC Reviewer | 质控审核 | ผู้ทบทวน QC

#### 中文
1. 查看 QC 规则命中情况、失控项和批次趋势。
2. 若 QC 不通过，禁止发布结果并要求重做。
3. QC 合格后执行 `Verify`。

#### English
1. Review QC rule hits, out-of-control items, and trend records.
2. If QC is rejected, block release and require rerun.
3. When QC is acceptable, run `Verify`.

#### ไทย
1. ตรวจสอบกฎ QC ที่ถูกทริกเกอร์, รายการนอกเกณฑ์ และแนวโน้ม
2. หาก QC ไม่ผ่าน ให้บล็อกการปล่อยผลและสั่งรันใหม่
3. เมื่อ QC ผ่านแล้วกด `Verify`

### 5.4 Medical Reviewer | 医学审核 | ผู้ทบทวนทางการแพทย์

#### 中文
1. 进行技术审核/医学审核（按系统配置）。
2. 需要时触发 AI 解读（手动或自动队列）。
3. 审批 AI 文本（Approve/Reject）。
4. 执行 `Release Report` 发布报告。

#### English
1. Complete technical/medical review steps.
2. Trigger AI interpretation (manual or queued auto mode).
3. Approve/reject AI interpretation.
4. Run `Release Report`.

#### ไทย
1. ทำขั้นตอนทบทวนทางเทคนิค/การแพทย์
2. เรียกใช้ AI แปลผล (แบบ manual หรือคิวอัตโนมัติ)
3. อนุมัติ/ปฏิเสธข้อความ AI
4. กด `Release Report`

### 5.5 Billing / Finance | 财务流程 | การเงิน

#### 中文
1. 维护报价版本与有效期。
2. 生成请求发票并跟踪支付状态。
3. 对账与异常支付处理。

#### English
1. Manage quote revisions and validity window.
2. Generate request invoices and track payment state.
3. Perform reconciliation and handle payment exceptions.

#### ไทย
1. จัดการเวอร์ชันใบเสนอราคาและวันหมดอายุ
2. สร้างใบแจ้งหนี้จากคำขอและติดตามสถานะชำระเงิน
3. กระทบยอดและจัดการข้อยกเว้นการชำระเงิน

### 5.6 Portal User (Individual/Institution) | Portal用户 | ผู้ใช้ Portal

#### 中文
1. 登录 Portal 看到 `Lab Reports` 与 `Test Requests`。
2. 提交申请（机构可按科室/医生选择）。
3. 查看流程状态与报告（H5默认）。
4. 下载 PDF（优先使用缓存版）。
5. 若开放，查看 AI 解读内容。

#### English
1. Log in to portal and access `Lab Reports` / `Test Requests`.
2. Submit requests (institutional users can choose department/physician).
3. Track request/sample states and open H5 report.
4. Download PDF report (cached file preferred).
5. View AI interpretation when approved and visible.

#### ไทย
1. เข้าสู่ Portal และใช้งาน `Lab Reports` / `Test Requests`
2. ส่งคำขอตรวจ (ลูกค้าองค์กรเลือกแผนก/แพทย์ได้)
3. ติดตามสถานะคำขอ/ตัวอย่าง และดูรายงาน H5
4. ดาวน์โหลดรายงาน PDF (ใช้ไฟล์แคชก่อน)
5. ดูผลแปล AI ได้เมื่ออนุมัติแล้ว

---

## 6. Key Quality/Compliance Controls | 质量与合规控制点 | จุดควบคุมคุณภาพ/การกำกับดูแล

### 中文
- 多公司隔离：所有核心模型按 `company_id` 隔离。
- 发布门禁：未审核、QC不通过不得发布。
- 修订机制：报告修订会提升 revision 并保留修订记录。
- 审计追踪：timeline / signoff / AI history / review log 完整记录。

### English
- Multi-company isolation on core models via `company_id`.
- Release gating: no release without required verification/QC.
- Amendment control: report revision increments with audit trail.
- Full traceability: timeline, sign-off, AI history, and review logs.

### ไทย
- แยกข้อมูลหลายบริษัทด้วย `company_id` ในโมเดลหลัก
- Gate การปล่อยผล: ต้องผ่านการทบทวน/QC ก่อนเสมอ
- ควบคุมการแก้ไขรายงาน: เพิ่ม revision และเก็บประวัติครบ
- ตรวจสอบย้อนหลังได้: timeline, signoff, AI history, review log

---

## 7. Go-Live Acceptance Checklist | 上线验收清单 | เช็กลิสต์ก่อน Go-Live

### 中文
1. 个人 Portal：申请->收样->出报告->H5/PDF可查。
2. 机构 Portal：批量申请5人以上，报告权限符合机构隔离。
3. AI：队列任务正常消费，失败重试正常。
4. 报告：模板、多语言、PDF下载均正常。
5. 权限：各角色菜单可见性与操作权限正确。

### English
1. Individual portal path passes end-to-end (request -> sample -> report -> H5/PDF).
2. Institutional batch request (>=5 patients) passes with correct visibility scope.
3. AI queue processing and retry are working.
4. Reports render correctly in template variants and multilingual mode.
5. Role permissions and menu visibility are validated.

### ไทย
1. เส้นทางผู้ใช้บุคคลผ่านครบ (request -> sample -> report -> H5/PDF)
2. ลูกค้าองค์กรส่งแบบ batch (>=5 คน) และสิทธิ์การมองเห็นถูกต้อง
3. คิว AI และการ retry ทำงานปกติ
4. รายงานแสดงผลถูกต้องทั้งเทมเพลตและหลายภาษา
5. สิทธิ์แต่ละบทบาทและเมนูถูกต้องตามที่ออกแบบ

---

## 8. New in 19.0.2.0.22 | 版本新增能力 | ความสามารถใหม่ในเวอร์ชัน 19.0.2.0.22

### 中文
1. 新增“动态表单”引擎：可将特定表单绑定到 Service/Panel，提交申请时必须填写。
2. 新增实验室原生 `Patient` 与 `Physician` 主数据模型，支持更完整字段管理。
3. 新增申请附件能力：Portal、内部工作台、外部API均可上传申请附件。
4. 安装顺序优化：修复全新安装时安全组/菜单加载顺序问题。

### English
1. Added dynamic form engine with per-service/per-panel required forms.
2. Added lab-native patient and physician master data models.
3. Added request attachments in portal, internal workbench, and external API.
4. Improved install order for security/menu loading on clean installs.

### ไทย
1. เพิ่มระบบ Dynamic Form ที่ผูกกับ Service/Panel และบังคับกรอกตอนส่งคำขอ
2. เพิ่มโมเดลข้อมูลหลักของผู้ป่วยและแพทย์ในฝั่งห้องปฏิบัติการ
3. เพิ่มการแนบไฟล์คำขอทั้งใน Portal, หลังบ้าน และ External API
4. ปรับลำดับการติดตั้งให้เสถียรขึ้นสำหรับการติดตั้งใหม่

---

## 9. Dynamic Form Configuration SOP | 动态表单配置SOP | SOP การตั้งค่า Dynamic Form

### 中文
1. 菜单：`Laboratory > Configuration > Test Catalog > Dynamic Forms`
2. 新建表单并新增字段（text/number/date/selection/boolean）。
3. 在 `Analysis Services` 或 `Analysis Panels` 中绑定所需表单。
4. 提交申请时，系统会自动校验必填字段并保存回答。

### English
1. Go to `Laboratory > Configuration > Test Catalog > Dynamic Forms`.
2. Create a form and define fields (text/number/date/selection/boolean).
3. Bind forms on service or panel configuration.
4. On request submit, required form answers are validated and stored.

### ไทย
1. ไปที่ `Laboratory > Configuration > Test Catalog > Dynamic Forms`
2. สร้างฟอร์มและกำหนดฟิลด์ (text/number/date/selection/boolean)
3. ผูกฟอร์มที่จำเป็นกับ service หรือ panel
4. ตอนส่งคำขอ ระบบจะตรวจสอบฟิลด์บังคับและบันทึกคำตอบอัตโนมัติ
