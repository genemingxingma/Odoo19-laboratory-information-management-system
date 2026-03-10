# Odoo shell script: quality baseline setup for demo/training
# Usage:
#   /Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
#   /Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
#   -c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
#   < /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_quality_baseline_local.py

from datetime import timedelta

from odoo import fields

company = env.company
summary = []


def log(msg):
    summary.append(msg)


def ensure(model, domain, vals):
    rec = env[model].sudo().search(domain, limit=1)
    if rec:
        rec.write(vals)
    else:
        rec = env[model].sudo().create(vals)
    return rec


def get_service(code, fallback_department=False):
    svc = env["lab.service"].sudo().search([("code", "=", code), ("company_id", "=", company.id)], limit=1)
    if not svc and fallback_department:
        svc = env["lab.service"].sudo().search([("department", "=", fallback_department), ("company_id", "=", company.id)], limit=1)
    return svc


# 1) Ensure quality-relevant services exist or fallback
svc_glu = get_service("GLU-FAST", "chemistry")
svc_alt = get_service("ALT-SER", "chemistry")
svc_std_ct = get_service("STD-CT-CT", "microbiology")
svc_hpv16 = get_service("HPV-16-GV", "microbiology")

if not svc_glu:
    svc_glu = ensure(
        "lab.service",
        [("code", "=", "GLU-FAST"), ("company_id", "=", company.id)],
        {
            "name": "Fasting Glucose",
            "code": "GLU-FAST",
            "department": "chemistry",
            "sample_type": "serum",
            "result_type": "numeric",
            "ref_min": 3.9,
            "ref_max": 6.1,
            "critical_min": 2.5,
            "critical_max": 20.0,
            "turnaround_hours": 8,
            "auto_verify_enabled": True,
            "list_price": 39.0,
            "company_id": company.id,
            "active": True,
        },
    )
if not svc_alt:
    svc_alt = ensure(
        "lab.service",
        [("code", "=", "ALT-SER"), ("company_id", "=", company.id)],
        {
            "name": "Alanine Aminotransferase",
            "code": "ALT-SER",
            "department": "chemistry",
            "sample_type": "serum",
            "result_type": "numeric",
            "ref_min": 0,
            "ref_max": 40,
            "critical_min": 0,
            "critical_max": 200,
            "turnaround_hours": 8,
            "auto_verify_enabled": True,
            "list_price": 35.0,
            "company_id": company.id,
            "active": True,
        },
    )
if not svc_std_ct:
    svc_std_ct = ensure(
        "lab.service",
        [("code", "=", "STD-CT-CT"), ("company_id", "=", company.id)],
        {
            "name": "Chlamydia trachomatis PCR Ct",
            "code": "STD-CT-CT",
            "department": "microbiology",
            "sample_type": "swab",
            "result_type": "numeric",
            "ref_min": 0,
            "ref_max": 45,
            "critical_min": 0,
            "critical_max": 45,
            "auto_binary_enabled": True,
            "auto_binary_cutoff": 33.0,
            "auto_binary_negative_when_gte": True,
            "turnaround_hours": 24,
            "list_price": 99.0,
            "company_id": company.id,
            "active": True,
        },
    )
if not svc_hpv16:
    svc_hpv16 = ensure(
        "lab.service",
        [("code", "=", "HPV-16-GV"), ("company_id", "=", company.id)],
        {
            "name": "HPV 16 Genotyping Gray Value",
            "code": "HPV-16-GV",
            "department": "microbiology",
            "sample_type": "cervical_swab",
            "result_type": "numeric",
            "ref_min": 0,
            "ref_max": 999999,
            "critical_min": 0,
            "critical_max": 999999,
            "auto_binary_enabled": True,
            "auto_binary_cutoff": 0.0,
            "auto_binary_negative_when_gte": False,
            "turnaround_hours": 24,
            "list_price": 88.0,
            "company_id": company.id,
            "active": True,
        },
    )

log("Quality services ensured for QC/EQA baselines")

# 2) QC materials with Westgard rule sets
rule_model = env["lab.qc.rule.library"].sudo()
rule_chem = rule_model.search([("code", "in", ["13s", "22s", "R4s", "41s", "10x"]), ("active", "=", True)])
rule_micro = rule_model.search([("code", "in", ["13s", "12s", "22s"]), ("active", "=", True)])

qc_material_model = env["lab.qc.material"].sudo()
materials = []
for code, name, svc, target, sd, lot, rules in [
    ("QC-GLU-L1", "Glucose Control Level 1", svc_glu, 5.2, 0.25, "GLU-QC-LOT-2026A", rule_chem),
    ("QC-ALT-L1", "ALT Control Level 1", svc_alt, 28.0, 2.1, "ALT-QC-LOT-2026A", rule_chem),
    ("QC-STD-CT", "STD CT Positive Control", svc_std_ct, 30.5, 1.2, "STD-QC-LOT-2026A", rule_micro),
]:
    mat = qc_material_model.search([("code", "=", code)], limit=1)
    vals = {
        "name": name,
        "code": code,
        "service_id": svc.id,
        "lot_number": lot,
        "target_value": target,
        "std_dev": sd,
        "rule_ids": [(6, 0, rules.ids)],
        "active": True,
        "note": "Baseline material for quality menu training.",
    }
    if mat:
        mat.write(vals)
    else:
        mat = qc_material_model.create(vals)
    materials.append(mat)

log("QC materials configured (chemistry + molecular)")

# 3) Generate recent QC runs (for trend, warning/reject examples)
qc_run_model = env["lab.qc.run"].sudo()
base = fields.Datetime.now() - timedelta(days=8)
for mat in materials:
    if qc_run_model.search_count([("qc_material_id", "=", mat.id)]) >= 12:
        continue
    offsets = [-0.8, -0.3, 0.2, 0.6, 0.1, -0.4, 0.9, 1.1, -1.0, 0.0, 2.6, 3.4]
    for idx, z in enumerate(offsets):
        run_time = base + timedelta(hours=12 * idx)
        value = mat.target_value + z * mat.std_dev
        qc_run_model.create(
            {
                "qc_material_id": mat.id,
                "run_date": run_time,
                "operator_id": env.user.id,
                "result_value": value,
                "note": "Demo baseline QC run",
            }
        )

for mat in materials:
    runs = qc_run_model.search([("qc_material_id", "=", mat.id)], order="run_date desc", limit=12)
    runs.action_capture_trend_snapshot()

log("QC runs seeded and daily snapshots captured")

# 4) QC trend profile and snapshot
trend_profile = ensure(
    "lab.qc.trend.profile",
    [("code", "=", "BASELINE-CORE")],
    {
        "name": "Baseline Core Trend",
        "code": "BASELINE-CORE",
        "service_ids": [(6, 0, [svc_glu.id, svc_alt.id, svc_std_ct.id, svc_hpv16.id])],
        "window_size": 20,
        "warning_sigma": 2.0,
        "reject_sigma": 3.0,
        "active": True,
        "note": "Global baseline trend profile for quality monitoring.",
    },
)

trend_snapshot = ensure(
    "lab.qc.trend.snapshot",
    [("profile_id", "=", trend_profile.id), ("state", "=", "draft")],
    {
        "profile_id": trend_profile.id,
        "summary": "Autogenerated baseline trend snapshot",
    },
)
trend_snapshot.action_capture()
trend_snapshot.action_publish()
log("QC trend profile/snapshot generated")

# 5) Quality program (yearly)
year = fields.Date.today().year
program = ensure(
    "lab.quality.program",
    [("year", "=", year), ("objective", "ilike", "Baseline quality program")],
    {
        "year": year,
        "owner_id": env.user.id,
        "objective": "Baseline quality program for ISO-style operational monitoring and continuous improvement.",
        "state": "draft",
    },
)
program.action_generate_default_lines()
for line in program.line_ids:
    line.write({"department": "microbiology" if "proficiency" in (line.code or "") else "general"})
if program.state == "draft":
    program.action_activate()

log("Quality program activated with default lines")

# 6) Internal audit sample
audit = ensure(
    "lab.quality.audit",
    [("program_id", "=", program.id), ("scope", "ilike", "molecular and chemistry process")],
    {
        "program_id": program.id,
        "audit_date": fields.Date.today(),
        "scope": "molecular and chemistry process, sample traceability, release gate checks",
        "lead_auditor_id": env.user.id,
        "summary": "Baseline audit for training environment.",
    },
)
if not audit.finding_ids:
    env["lab.quality.audit.finding"].sudo().create(
        {
            "audit_id": audit.id,
            "title": "Inconsistent reagent lot verification timestamp",
            "description": "Two sample analyses lacked timestamp alignment in lot verification.",
            "severity": "minor",
            "owner_id": env.user.id,
            "target_date": fields.Date.add(fields.Date.today(), days=7),
            "corrective_action": "Enable mandatory timestamp sync check in pre-release checklist.",
        }
    )
if audit.state == "draft":
    audit.action_start()
if audit.state == "running":
    audit.action_complete()
for finding in audit.finding_ids.filtered(lambda f: f.state != "closed"):
    finding.action_implement()
    finding.action_verify()
    finding.action_close()
if audit.state == "completed":
    audit.action_close()

log("Internal audit closed with one CAPA-style finding")

# 7) Training sample
training = ensure(
    "lab.quality.training",
    [("program_id", "=", program.id), ("topic", "=", "PCR contamination control and release gate")],
    {
        "program_id": program.id,
        "topic": "PCR contamination control and release gate",
        "training_date": fields.Date.today(),
        "trainer_id": env.user.id,
        "duration_hour": 1.5,
        "authorization_role": "analyst",
        "authorization_service_ids": [(6, 0, [svc_std_ct.id, svc_hpv16.id])],
        "authorization_effective_months": 12,
        "state": "draft",
        "note": "Quality baseline training session.",
    },
)
if not training.attendee_ids:
    env["lab.quality.training.attendee"].sudo().create(
        {
            "training_id": training.id,
            "user_id": env.user.id,
            "attended": True,
            "score": 95.0,
            "comment": "Demo pass",
        }
    )
if training.state == "draft":
    training.action_schedule()
if training.state == "scheduled":
    training.action_done()

log("Training sample created and completed")

# 8) KPI snapshot capture
env["lab.quality.kpi.snapshot"].sudo().action_capture_kpi()
log("Quality KPI snapshot captured")

# 9) EQA schemes/rounds (chem + micro)
eqa_scheme_model = env["lab.eqa.scheme"].sudo()
chem_scheme = ensure(
    "lab.eqa.scheme",
    [("code", "=", "EQA-CHEM-CORE")],
    {
        "name": "Chemistry Core EQA",
        "code": "EQA-CHEM-CORE",
        "provider": "CAP-like Demo Provider",
        "department": "chemistry",
        "service_ids": [(6, 0, [svc_glu.id, svc_alt.id])],
        "active": True,
        "note": "Baseline chemistry EQA for learning.",
    },
)
micro_scheme = ensure(
    "lab.eqa.scheme",
    [("code", "=", "EQA-MICRO-MPX")],
    {
        "name": "Molecular PCR EQA",
        "code": "EQA-MICRO-MPX",
        "provider": "Molecular PT Demo Provider",
        "department": "microbiology",
        "service_ids": [(6, 0, [svc_std_ct.id, svc_hpv16.id])],
        "active": True,
        "note": "Baseline molecular EQA for learning.",
    },
)

round_date = fields.Date.today().replace(day=1)
rounds = []
for scheme, suffix in [(chem_scheme, "CHEM"), (micro_scheme, "MICRO")]:
    rnd = env["lab.eqa.round"].sudo().search(
        [("scheme_id", "=", scheme.id), ("name", "=", "2026-%s-01" % suffix)],
        limit=1,
    )
    if not rnd:
        rnd = env["lab.eqa.round"].sudo().create(
            {
                "name": "2026-%s-01" % suffix,
                "scheme_id": scheme.id,
                "sample_date": round_date,
                "due_date": fields.Date.add(round_date, days=14),
            }
        )
    if not rnd.result_ids:
        for svc in scheme.service_ids:
            expected = 5.5 if svc.code == "GLU-FAST" else (28.0 if svc.code == "ALT-SER" else (31.0 if "STD" in svc.code else 1.2))
            reported = expected * 1.03
            env["lab.eqa.result"].sudo().create(
                {
                    "round_id": rnd.id,
                    "service_id": svc.id,
                    "expected_value": expected,
                    "reported_value": reported,
                    "tolerance": 0.08 if svc.code in ("GLU-FAST", "ALT-SER") else 0.2,
                    "note": "Baseline EQA result line",
                }
            )
    if rnd.state == "draft":
        rnd.action_submit()
    if rnd.state == "submitted":
        rnd.action_evaluate()
    if rnd.state == "evaluated":
        rnd.action_close()
    rounds.append(rnd)

log("EQA schemes and one closed round per scheme configured")

# 10) EQA closure and compliance reports
period_start = fields.Date.today().replace(day=1)
period_end = fields.Date.today()

closure_report = env["lab.eqa.closure.report"].sudo().search(
    [("period_start", "=", period_start), ("period_end", "=", period_end)],
    limit=1,
)
if not closure_report:
    closure_report = env["lab.eqa.closure.report"].sudo().create({"period_start": period_start, "period_end": period_end})
closure_report.action_generate()
closure_report.action_publish()

compliance = env["lab.compliance.snapshot"].sudo().search(
    [("period_start", "=", period_start), ("period_end", "=", period_end)],
    limit=1,
)
if not compliance:
    compliance = env["lab.compliance.snapshot"].sudo().create({"period_start": period_start, "period_end": period_end})
compliance.action_generate()
compliance.action_publish()

audit_report = env["lab.compliance.audit.report"].sudo().search(
    [("period_start", "=", period_start), ("period_end", "=", period_end), ("department", "=", "microbiology")],
    limit=1,
)
if not audit_report:
    audit_report = env["lab.compliance.audit.report"].sudo().create(
        {
            "period_start": period_start,
            "period_end": period_end,
            "department": "microbiology",
            "conclusion": "Baseline compliance report for molecular workflow.",
        }
    )
audit_report.action_generate()
audit_report.action_approve()

log("Compliance snapshot, EQA closure report, and compliance audit report generated")

# 11) Method validation samples
validation_model = env["lab.method.validation"].sudo()
for svc, version in [(svc_glu, "GLU-V1.0"), (svc_std_ct, "STD-CT-V1.0")]:
    mv = validation_model.search([("service_id", "=", svc.id), ("method_version", "=", version)], limit=1)
    vals = {
        "service_id": svc.id,
        "method_version": version,
        "validation_type": "verification",
        "plan_note": "Baseline verification protocol",
        "precision_plan": "Run repeatability at low/normal/high controls, n>=20",
        "accuracy_plan": "Compare with peer method / assigned target",
        "linearity_plan": "5-point dilution linearity",
        "lod_loq_plan": "20 blank + low-level replicates",
        "reference_interval_plan": "Adopt verified interval from kit IFU",
        "precision_result": "CV within acceptance",
        "accuracy_result": "Bias within acceptance",
        "linearity_result": "R2 >= 0.99",
        "lod_loq_result": "Within claimed range",
        "reference_interval_result": "Verified",
        "summary_result": "Method acceptable for routine release.",
        "acceptance_criteria": "CV<=5%, Bias<=10%, Linearity R2>=0.99",
        "overall_pass": True,
        "effective_from": fields.Date.today(),
        "effective_to": fields.Date.add(fields.Date.today(), years=1),
        "review_interval_months": 12,
    }
    if mv:
        mv.write(vals)
    else:
        mv = validation_model.create(vals)
    if mv.state in ("draft", "in_progress", "rejected"):
        mv.action_submit()
    if mv.state == "pending_approval":
        mv.action_approve()

log("Method validation baselines approved")

print("=" * 80)
print("QUALITY BASELINE CONFIGURATION COMPLETED")
print("Company:", company.name)
for line in summary:
    print("-", line)
print("Menu learning order:")
print("  1) Quality > QC Materials / QC Runs / QC Daily Snapshots")
print("  2) Quality > QC Trend Profiles / QC Trend Snapshots")
print("  3) Quality > Quality Programs / Internal Audits / Training Sessions / KPI Snapshots")
print("  4) Quality > EQA Schemes / EQA Rounds / EQA Closure Reports")
print("  5) Quality > Compliance Reports / Compliance Audit Reports")
print("  6) Quality > Method Validation")
print("=" * 80)
env.cr.commit()
