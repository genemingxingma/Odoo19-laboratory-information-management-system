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
