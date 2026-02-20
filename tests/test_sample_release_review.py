from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestSampleReleaseReview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.partner_patient = cls.env["res.partner"].create(
            {
                "name": "Portal Patient",
                "lang": "en_US",
            }
        )
        cls.partner_client = cls.env["res.partner"].create(
            {
                "name": "City Medical Center",
                "is_company": True,
            }
        )
        cls.service = cls.env["lab.service"].create(
            {
                "name": "CRP",
                "code": "REL-CRP",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "unit": "mg/L",
                "ref_min": 0,
                "ref_max": 5,
                "turnaround_hours": 12,
                "list_price": 48,
            }
        )
        cls.service_qc = cls.env["lab.service"].create(
            {
                "name": "PCR QC Gate",
                "code": "REL-PCR-QC",
                "department": "immunology",
                "sample_type": "swab",
                "result_type": "numeric",
                "unit": "Ct",
                "ref_min": 0,
                "ref_max": 45,
                "turnaround_hours": 24,
                "require_qc": True,
                "list_price": 88,
            }
        )
        cls.service_validation = cls.env["lab.service"].create(
            {
                "name": "Validation Gate Service",
                "code": "REL-VAL-GATE",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "unit": "U/L",
                "ref_min": 0,
                "ref_max": 100,
                "turnaround_hours": 24,
                "require_method_validation": True,
                "list_price": 66,
            }
        )
        base_group = cls.env.ref("base.group_user")
        cls.group_lab_reviewer = cls.env.ref("laboratory_management.group_lab_reviewer")
        cls.group_lab_manager = cls.env.ref("laboratory_management.group_lab_manager")
        cls.analyst_user = cls.env["res.users"].create(
            {
                "name": "Release Analyst",
                "login": "release_analyst",
                "email": "release_analyst@example.com",
                "group_ids": [(6, 0, [base_group.id])],
            }
        )
        cls.tech_reviewer_user = cls.env["res.users"].create(
            {
                "name": "Tech Reviewer",
                "login": "release_tech_reviewer",
                "email": "release_tech_reviewer@example.com",
                "group_ids": [(6, 0, [cls.group_lab_reviewer.id])],
            }
        )
        cls.med_reviewer_user = cls.env["res.users"].create(
            {
                "name": "Med Reviewer",
                "login": "release_med_reviewer",
                "email": "release_med_reviewer@example.com",
                "group_ids": [(6, 0, [cls.group_lab_manager.id])],
            }
        )

    def _create_request(self):
        request = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner_patient.id,
                "request_type": "institution",
                "client_partner_id": self.partner_client.id,
                "patient_id": self.partner_patient.id,
                "patient_name": self.partner_patient.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "line_type": "service",
                            "service_id": self.service.id,
                            "quantity": 1,
                            "unit_price": 48,
                        },
                    )
                ],
            }
        )
        request.action_submit()
        request.action_prepare_quote()
        request.action_approve_quote()
        request.action_create_samples()
        return request

    def _prepare_verified_sample(self):
        request = self._create_request()
        sample = request.sample_ids[:1]
        sample.action_receive()
        sample.action_start()
        analysis = sample.analysis_ids[:1]
        analysis.result_value = "9.5"
        analysis.action_verify_result()

        now = fields.Datetime.now()
        # Write explicit approved review state to unblock release in deterministic way.
        sample.write(
            {
                "technical_review_state": "approved",
                "technical_reviewer_id": self.env.user.id,
                "technical_reviewed_at": now,
                "medical_review_state": "approved",
                "medical_reviewer_id": self.env.user.id,
                "medical_reviewed_at": now,
            }
        )
        return sample

    def test_01_release_creates_dispatch_for_patient_and_client(self):
        sample = self._prepare_verified_sample()
        sample.action_release_report()

        self.assertEqual(sample.state, "reported")
        self.assertEqual(sample.report_publication_state, "active")
        self.assertEqual(len(sample.dispatch_ids), 2)
        self.assertEqual(set(sample.dispatch_ids.mapped("state")), {"sent"})

        dispatch_partners = set(sample.dispatch_ids.mapped("partner_id"))
        self.assertIn(self.partner_patient, dispatch_partners)
        self.assertIn(self.partner_client, dispatch_partners)

    def test_02_withdraw_requires_reason(self):
        sample = self._prepare_verified_sample()
        sample.action_release_report()

        sample.report_withdraw_input = False
        with self.assertRaises(UserError):
            sample.action_withdraw_report()

    def test_03_withdraw_cancels_active_dispatches(self):
        sample = self._prepare_verified_sample()
        sample.action_release_report()

        sample.report_withdraw_input = "Corrective amendment"
        sample.action_withdraw_report()

        self.assertEqual(sample.report_publication_state, "withdrawn")
        self.assertEqual(sample.report_withdrawn_reason, "Corrective amendment")
        self.assertEqual(set(sample.dispatch_ids.mapped("state")), {"cancel"})

    def test_04_reissue_moves_back_to_verified_and_increments_revision(self):
        sample = self._prepare_verified_sample()
        sample.action_release_report()
        rev_before = sample.report_revision

        sample.report_withdraw_input = "Recheck analyte"
        sample.action_withdraw_report()
        sample.action_reissue_report()

        self.assertEqual(sample.state, "verified")
        self.assertEqual(sample.report_publication_state, "active")
        self.assertEqual(sample.report_revision, rev_before + 1)
        self.assertTrue(sample.is_amended)
        self.assertEqual(sample.technical_review_state, "pending")
        self.assertEqual(sample.medical_review_state, "pending")

    def test_05_print_withdrawn_report_blocked(self):
        sample = self._prepare_verified_sample()
        sample.action_release_report()

        sample.report_withdraw_input = "Hide pending update"
        sample.action_withdraw_report()

        with self.assertRaises(UserError):
            sample.action_print_report()

    def test_06_ai_output_language_from_patient_lang(self):
        sample = self._prepare_verified_sample()
        sample.patient_id.lang = "zh_CN"
        self.assertEqual(sample._get_output_language(), "Chinese")

        sample.patient_id.lang = "th_TH"
        self.assertEqual(sample._get_output_language(), "Thai")

        sample.patient_id.lang = "en_US"
        self.assertEqual(sample._get_output_language(), "English")

    def test_07_ai_prompt_contains_key_snapshot_data(self):
        sample = self._prepare_verified_sample()
        sample.action_release_report()

        prompt, language = sample._build_ai_prompt()
        self.assertEqual(language, "English")
        self.assertIn(sample.name, prompt)
        self.assertIn("Analysis Results", prompt)
        self.assertIn("Abnormal Items", prompt)

    def test_08_portal_visibility_requires_approved_review(self):
        sample = self._prepare_verified_sample()
        sample.write(
            {
                "ai_interpretation_state": "done",
                "ai_interpretation_text": "Educational summary",
                "ai_review_state": "pending",
            }
        )
        sample._compute_ai_portal_visible()
        self.assertFalse(sample.ai_portal_visible)

        sample.ai_review_state = "approved"
        sample._compute_ai_portal_visible()
        self.assertTrue(sample.ai_portal_visible)

    def test_09_default_dispatch_creation_is_idempotent(self):
        sample = self._prepare_verified_sample()
        sample.action_release_report()
        count_before = len(sample.dispatch_ids)

        sample._create_default_dispatches()
        self.assertEqual(len(sample.dispatch_ids), count_before)

    def test_10_release_blocked_when_dual_review_incomplete(self):
        sample = self._prepare_verified_sample()
        sample.write(
            {
                "technical_review_state": "pending",
                "medical_review_state": "approved",
            }
        )

        with self.assertRaises(UserError):
            sample.action_release_report()

    def test_11_release_blocked_by_iso_gate_when_qc_required_without_pass(self):
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "1")
        sample = self.env["lab.sample"].create(
            {
                "patient_id": self.partner_patient.id,
                "analysis_ids": [
                    (
                        0,
                        0,
                        {
                            "service_id": self.service_qc.id,
                            "state": "verified",
                            "result_value": "30.0",
                            "analyst_id": self.env.user.id,
                        },
                    )
                ],
                "state": "verified",
                "technical_review_state": "approved",
                "technical_reviewer_id": self.env.user.id,
                "technical_reviewed_at": fields.Datetime.now(),
                "medical_review_state": "approved",
                "medical_reviewer_id": self.env.user.id,
                "medical_reviewed_at": fields.Datetime.now(),
            }
        )
        with self.assertRaises(UserError):
            sample.action_release_report()
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "0")

    def test_12_iso_reviewer_separation_blocks_same_user_dual_approval(self):
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_reviewer_separation_enabled", "1")
        sample = self._prepare_verified_sample()
        sample.write(
            {
                "technical_review_state": "pending",
                "technical_reviewer_id": False,
                "medical_review_state": "pending",
                "medical_reviewer_id": False,
            }
        )
        sample.action_approve_technical_review()
        with self.assertRaises(UserError):
            sample.action_approve_medical_review()
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_reviewer_separation_enabled", "0")

    def test_13_release_blocked_when_required_method_validation_missing(self):
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "1")
        sample = self.env["lab.sample"].create(
            {
                "patient_id": self.partner_patient.id,
                "analysis_ids": [
                    (
                        0,
                        0,
                        {
                            "service_id": self.service_validation.id,
                            "state": "verified",
                            "result_value": "50.0",
                            "analyst_id": self.env.user.id,
                        },
                    )
                ],
                "state": "verified",
                "technical_review_state": "approved",
                "technical_reviewer_id": self.env.user.id,
                "technical_reviewed_at": fields.Datetime.now(),
                "medical_review_state": "approved",
                "medical_reviewer_id": self.env.user.id,
                "medical_reviewed_at": fields.Datetime.now(),
            }
        )
        with self.assertRaises(UserError):
            sample.action_release_report()
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "0")

    def test_14_release_allows_when_required_method_validation_is_approved(self):
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "1")
        self.env["lab.method.validation"].create(
            {
                "service_id": self.service_validation.id,
                "method_version": "v1",
                "validation_type": "verification",
                "overall_pass": True,
                "state": "approved",
                "effective_from": fields.Date.today(),
            }
        )
        sample = self.env["lab.sample"].create(
            {
                "patient_id": self.partner_patient.id,
                "analysis_ids": [
                    (
                        0,
                        0,
                        {
                            "service_id": self.service_validation.id,
                            "state": "verified",
                            "result_value": "48.0",
                            "analyst_id": self.env.user.id,
                        },
                    )
                ],
                "state": "verified",
                "technical_review_state": "approved",
                "technical_reviewer_id": self.env.user.id,
                "technical_reviewed_at": fields.Datetime.now(),
                "medical_review_state": "approved",
                "medical_reviewer_id": self.env.user.id,
                "medical_reviewed_at": fields.Datetime.now(),
            }
        )
        sample.action_release_report()
        self.assertEqual(sample.state, "reported")
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "0")

    def test_15_release_blocked_when_personnel_service_authorization_missing(self):
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "1")
        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.iso15189_personnel_authorization_enabled", "1"
        )
        sample = self.env["lab.sample"].create(
            {
                "patient_id": self.partner_patient.id,
                "analysis_ids": [
                    (
                        0,
                        0,
                        {
                            "service_id": self.service.id,
                            "state": "verified",
                            "result_value": "9.5",
                            "analyst_id": self.analyst_user.id,
                        },
                    )
                ],
                "state": "verified",
                "technical_review_state": "approved",
                "technical_reviewer_id": self.tech_reviewer_user.id,
                "technical_reviewed_at": fields.Datetime.now(),
                "medical_review_state": "approved",
                "medical_reviewer_id": self.med_reviewer_user.id,
                "medical_reviewed_at": fields.Datetime.now(),
            }
        )
        with self.assertRaises(UserError):
            sample.action_release_report()
        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.iso15189_personnel_authorization_enabled", "0"
        )
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "0")

    def test_16_release_allows_when_personnel_service_authorization_exists(self):
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "1")
        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.iso15189_personnel_authorization_enabled", "1"
        )
        sample = self.env["lab.sample"].create(
            {
                "patient_id": self.partner_patient.id,
                "analysis_ids": [
                    (
                        0,
                        0,
                        {
                            "service_id": self.service.id,
                            "state": "verified",
                            "result_value": "9.5",
                            "analyst_id": self.analyst_user.id,
                        },
                    )
                ],
                "state": "verified",
                "technical_review_state": "approved",
                "technical_reviewer_id": self.tech_reviewer_user.id,
                "technical_reviewed_at": fields.Datetime.now(),
                "medical_review_state": "approved",
                "medical_reviewer_id": self.med_reviewer_user.id,
                "medical_reviewed_at": fields.Datetime.now(),
            }
        )
        auth_obj = self.env["lab.service.authorization"]
        auth_obj.create(
            {
                "user_id": self.analyst_user.id,
                "role": "analyst",
                "service_id": self.service.id,
                "state": "approved",
            }
        )
        auth_obj.create(
            {
                "user_id": self.tech_reviewer_user.id,
                "role": "technical_reviewer",
                "service_id": self.service.id,
                "state": "approved",
            }
        )
        auth_obj.create(
            {
                "user_id": self.med_reviewer_user.id,
                "role": "medical_reviewer",
                "service_id": self.service.id,
                "state": "approved",
            }
        )
        sample.action_release_report()
        self.assertEqual(sample.state, "reported")
        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.iso15189_personnel_authorization_enabled", "0"
        )
        self.env["ir.config_parameter"].sudo().set_param("laboratory_management.iso15189_release_gate_enabled", "0")
