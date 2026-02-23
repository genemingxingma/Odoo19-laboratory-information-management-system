from odoo import fields, models


class LabRetestPolicyMasterData(models.Model):
    _inherit = "lab.retest.policy"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
        required=True,
    )


class LabDepartmentSopMasterData(models.Model):
    _inherit = "lab.department.sop"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
        required=True,
    )
    sample_type = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_sample_type(),
        default="all",
        required=True,
    )
    priority = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_priority(),
        default="all",
        required=True,
    )


class LabSopRetestStrategyMasterData(models.Model):
    _inherit = "lab.sop.retest.strategy"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
        required=True,
    )
    sample_type = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_sample_type(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_sample_type_code(),
        required=True,
    )


class LabSopExecutionDashboardWizardMasterData(models.TransientModel):
    _inherit = "lab.sop.execution.dashboard.wizard"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
        required=True,
    )


class LabSopWorkflowProfileMasterData(models.Model):
    _inherit = "lab.sop.workflow.profile"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )
    sample_type = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_sample_type(),
        default="all",
        required=True,
    )
    priority = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_priority(),
        default="all",
        required=True,
    )
    request_type = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_request_type(),
        default="all",
        required=True,
    )


class LabSopDecisionThresholdProfileMasterData(models.Model):
    _inherit = "lab.sop.decision.threshold.profile"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )


class LabSopExceptionDecisionMasterData(models.Model):
    _inherit = "lab.sop.exception.decision"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )
    sample_type = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_sample_type(),
        default="all",
        required=True,
    )
    priority = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_priority(),
        default="all",
        required=True,
    )
    request_type = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_request_type(),
        default="all",
        required=True,
    )


class LabDepartmentExceptionTemplateMasterData(models.Model):
    _inherit = "lab.department.exception.template"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )
    sample_type = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_sample_type(),
        default="all",
        required=True,
    )
    task_priority = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_priority(),
        default="all",
        required=True,
    )


class LabTaskSlaPolicyMasterData(models.Model):
    _inherit = "lab.task.sla.policy"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )
    priority = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_priority(),
        default="all",
        required=True,
    )


class LabWorkstationTaskMasterData(models.Model):
    _inherit = "lab.workstation.task"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )
    priority = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_priority(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_priority_code(),
        required=True,
    )


class LabSopBranchRuleMasterData(models.Model):
    _inherit = "lab.sop.branch.rule"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )
    sample_type = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_sample_type(),
        default="all",
        required=True,
    )
    task_priority = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_priority(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_priority_code(),
    )


class LabTaskBoardWizardMasterData(models.TransientModel):
    _inherit = "lab.task.board.wizard"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
        required=True,
    )


class LabDepartmentQueueRuleMasterData(models.Model):
    _inherit = "lab.department.queue.rule"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )
    priority = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_priority(),
        default="all",
        required=True,
    )


class LabDepartmentWorkbenchWizardMasterData(models.TransientModel):
    _inherit = "lab.department.workbench.wizard"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
        required=True,
    )


class LabComplianceAuditReportMasterData(models.Model):
    _inherit = "lab.compliance.audit.report"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
    )


class LabDepartmentWorkbenchRuleRunMasterData(models.Model):
    _inherit = "lab.department.workbench.rule.run"

    wizard_department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )


class LabWorkstationRoleProfileMasterData(models.Model):
    _inherit = "lab.workstation.role.profile"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )


class LabWorkstationAssignmentRuleMasterData(models.Model):
    _inherit = "lab.workstation.assignment.rule"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )
    priority = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_priority(),
        default="all",
        required=True,
    )


class LabWorkstationMyWorkbenchWizardMasterData(models.TransientModel):
    _inherit = "lab.workstation.my.workbench.wizard"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
        required=True,
    )


class LabInstrumentMasterData(models.Model):
    _inherit = "lab.instrument"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
    )


class LabPersonnelMatrixRunMasterData(models.Model):
    _inherit = "lab.personnel.matrix.run"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
    )


class LabWorksheetMasterData(models.Model):
    _inherit = "lab.worksheet"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_department_code(),
        required=True,
    )


class LabEqaSchemeMasterData(models.Model):
    _inherit = "lab.eqa.scheme"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        required=True,
    )


class LabQualityProgramLineMasterData(models.Model):
    _inherit = "lab.quality.program.line"

    department = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_department(),
        default="general",
        required=True,
    )


class LabRetestAnalyticsReportMasterData(models.Model):
    _inherit = "lab.retest.analytics.report"

    department = fields.Selection(
        selection=lambda self: [("all", "All")] + self.env["lab.master.data.mixin"]._selection_department(),
        default="all",
        required=True,
    )
