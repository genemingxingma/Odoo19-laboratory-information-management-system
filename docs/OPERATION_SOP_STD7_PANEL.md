# STD7 Multiplex PCR SOP (CN / EN / TH)

## CN - 标准操作流程

### 1) 适用范围
用于同一多重PCR试剂盒（STD7）支持 3/4/6/7 项套餐配置与运行。

### 2) 前置条件
- 已安装模块：`laboratory_management`
- 角色：Manager / Reviewer / Reception / Portal
- 如需AI解读，已配置 AI provider

### 3) 配置步骤
1. 配置 7 个 Service（CT/NG/UU/HSV1/HSV2/CA/GV）
2. 创建 Assay Kit：`STD7-MPX-KIT`
3. 创建 Reagent Lot（Scope=`Panel`）
4. 创建 Panel：`STD7-3P/4P/6P/7P`

关键设置：
- `Require Reagent Lot = True`
- `Result Type = Numeric`
- 可选 `Auto binary cutoff = 33`

### 4) 流程步骤
1. Portal/后台创建申请（选某个STD套餐）
2. Submit -> Quote -> Approve -> Create Sample
3. 收样并开始检测，给样本分析项绑定 panel lot
4. 录结果并完成验证
5. 通过技术/医学审核后发布报告
6. 可触发 AI 解读并审批后在 portal 显示

### 5) 验证清单
- 样本状态 = `reported`
- 同一样本所有分析项使用同一 panel lot
- 试剂消耗按样本+批号记一次
- portal 权限域正确
- AI 状态为 done/approved/portal visible（如启用）

---

## EN - Standard Operating Procedure

### 1) Scope
Operate one STD7 multiplex PCR kit as multiple packages (3/4/6/7 analytes).

### 2) Preconditions
- Module installed: `laboratory_management`
- Roles available: manager/reviewer/reception/portal
- AI provider configured if interpretation is needed

### 3) Configuration
1. Create 7 services (CT/NG/UU/HSV1/HSV2/CA/GV)
2. Create assay kit `STD7-MPX-KIT`
3. Create panel-scope reagent lot
4. Create panels `STD7-3P/4P/6P/7P`

Required options:
- `Require Reagent Lot = True`
- `Result Type = Numeric`
- Optional binary cutoff (example `33`)

### 4) Workflow
1. Create request from portal/backoffice with one STD package
2. `Submit -> Quote -> Approve -> Create Sample`
3. Receive/start sample and assign panel lot
4. Enter results and verify
5. Complete release gate and release report
6. Trigger/approve AI interpretation for portal visibility

### 5) Validation checklist
- Sample state is `reported`
- All analytes in same sample share one panel lot
- One usage record per sample+lot
- Portal domain visibility is correct
- AI flags are done/approved/visible when enabled

---

## TH - ขั้นตอนปฏิบัติงานมาตรฐาน

### 1) ขอบเขต
ใช้ชุดตรวจ STD7 multiplex PCR ชุดเดียวเพื่อทำแพ็กเกจ 3/4/6/7 รายการ

### 2) เงื่อนไขก่อนเริ่ม
- ติดตั้งโมดูล `laboratory_management`
- มีสิทธิ์ผู้ใช้ครบ (manager/reviewer/reception/portal)
- ตั้งค่า AI provider แล้ว (ถ้าต้องการแปลผลด้วย AI)

### 3) การตั้งค่า
1. สร้าง service 7 รายการ (CT/NG/UU/HSV1/HSV2/CA/GV)
2. สร้าง assay kit `STD7-MPX-KIT`
3. สร้าง reagent lot แบบ `Panel`
4. สร้าง panel `STD7-3P/4P/6P/7P`

ค่าที่ต้องตั้ง:
- `Require Reagent Lot = True`
- `Result Type = Numeric`
- ตั้ง cutoff อัตโนมัติได้ (ตัวอย่าง `33`)

### 4) ขั้นตอนทำงาน
1. สร้างคำขอจาก portal/backoffice
2. `Submit -> Quote -> Approve -> Create Sample`
3. รับตัวอย่างและผูก panel lot
4. บันทึกผลและ verify
5. ผ่าน technical/medical review แล้ว release report
6. เรียกใช้และอนุมัติ AI interpretation เพื่อแสดงใน portal

### 5) เช็กลิสต์ตรวจสอบ
- สถานะตัวอย่างเป็น `reported`
- analyte ในตัวอย่างเดียวกันใช้ panel lot เดียวกัน
- มีบันทึกการใช้ reagent 1 รายการต่อ sample+lot
- สิทธิ์การมองเห็นใน portal ถูกต้อง
- สถานะ AI เป็น done/approved/visible (เมื่อเปิดใช้งาน)
