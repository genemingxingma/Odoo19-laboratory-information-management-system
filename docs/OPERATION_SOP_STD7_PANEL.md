# Laboratory Operation SOP: STD7 Multiplex PCR Panel (3/4/6/7 Packages)

## 1. Scope
This SOP defines how to configure and operate one multiplex PCR assay kit (STD7) for multiple package combinations (3-item, 4-item, 6-item, 7-item) in the Laboratory Management module.

## 2. Preconditions
- Module installed: `laboratory_management`
- User roles ready: Lab Manager / Reviewer / Reception / Portal User
- AI provider configured (OpenAI / OpenAI-compatible / Ollama) if AI interpretation is required

## 3. Master Data Setup

### 3.1 Configure Services (7 analytes)
Menu: `Laboratory > Configuration > Services`

Create 7 services (example codes):
- `STD7-CT` Chlamydia trachomatis PCR
- `STD7-NG` Neisseria gonorrhoeae PCR
- `STD7-UU` Ureaplasma urealyticum PCR
- `STD7-HSV1` HSV-I PCR
- `STD7-HSV2` HSV-II PCR
- `STD7-CA` Candida albicans PCR
- `STD7-GV` Gardnerella vaginalis PCR

Required options:
- `Require Reagent Lot = True`
- `Result Type = Numeric`
- (Optional) Auto binary cutoff rule (example: cutoff 33)

### 3.2 Configure Assay Kit (Multiplex panel)
Menu: `Laboratory > Configuration > Assay Kits`

Create assay kit:
- Name: `STD7 Multiplex PCR Kit`
- Code: `STD7-MPX-KIT`
- Method: `Multiplex PCR`
- Covered Services: select all 7 STD services

### 3.3 Configure Reagent Lot (Panel scope)
Menu: `Laboratory > Configuration > Reagent Lots`

Create lot:
- Scope: `Panel`
- Assay Kit: `STD7-MPX-KIT`
- Lot Number: e.g. `STD7-PANEL-LOT-A1`
- Expiry Date / Reactions Total / Vendor

Important logic:
- One sample using this panel lot consumes reagent once (not once per analyte).

### 3.4 Configure Package Profiles (3/4/6/7)
Menu: `Laboratory > Configuration > Profiles`

Create profiles:
- `STD7-3P` (3 analytes)
- `STD7-4P` (4 analytes)
- `STD7-6P` (6 analytes)
- `STD7-7P` (7 analytes)

Each profile includes subset services from the same STD7 panel.

## 4. End-to-End Workflow

### 4.1 Request creation
- Portal user creates test request using one package profile.
- Backoffice transitions request: `Submit -> Quote -> Approve -> Create Sample`.

### 4.2 Sample and analysis
- Receive/start sample.
- Assign panel lot to one analysis line.
- System auto-propagates the same panel lot to all covered analytes in the same sample.
- Enter results and mark done.

### 4.3 Verification and report release
- Verify sample.
- Complete technical/medical review if release gate enabled.
- Release report (`state = reported`).

### 4.4 AI interpretation
- Trigger AI interpretation manually or from portal/report action.
- Approve AI interpretation to expose in portal/report:
  - `AI state = done`
  - `AI review state = approved`
  - `AI visible in portal = True`

## 5. Validation Checklist
For each sample in STD7 package flow:
- Sample state is `reported`
- All analysis lines use same panel lot
- Reagent usage has one posted usage record per sample+lot
- Request and sample visible under intended portal partner domain
- (If AI required) AI generated and approved

## 6. Troubleshooting

### 6.1 Portal cannot see request/report
Check:
- Portal login account (actual login, not display name)
- Partner/commercial partner linkage
- Domain logic:
  - Requests: requester/client child_of portal commercial partner
  - Samples: patient/client child_of portal commercial partner
- Report publication state and dispatch status

### 6.2 AI generated but not shown in portal
Check:
- `ai_interpretation_state = done`
- `ai_review_state = approved`
- `ai_portal_visible = True`
- User browser cache (hard refresh)

### 6.3 Reagent usage incorrect
Check:
- Lot scope is `Panel`
- Lot is not expired
- Assay kit covers all target analytes

## 7. Reference Demo Records (server)
Committed demo set:
- Requests: `TRQ2602-00016` to `TRQ2602-00019`
- Samples: `ACC2602-00016` to `ACC2602-00019`
- Packages: `STD7-3P`, `STD7-4P`, `STD7-6P`, `STD7-7P`

