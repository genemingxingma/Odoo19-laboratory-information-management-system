from odoo.tests.common import TransactionCase


class TestBinaryInterpretationRule(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.patient = cls.env["res.partner"].create({"name": "Binary Rule Patient"})
        cls.service = cls.env["lab.service"].create(
            {
                "name": "HPV Ct",
                "code": "HPV_CT",
                "department": "immunology",
                "sample_type": "swab",
                "result_type": "numeric",
                "ref_min": 0,
                "ref_max": 45,
                "auto_binary_enabled": True,
                "auto_binary_cutoff": 33.0,
                "auto_binary_negative_when_gte": True,
            }
        )

    def _new_analysis(self, value):
        sample = self.env["lab.sample"].create(
            {
                "patient_id": self.patient.id,
                "analysis_ids": [
                    (
                        0,
                        0,
                        {
                            "service_id": self.service.id,
                            "result_value": str(value),
                            "state": "assigned",
                        },
                    )
                ],
            }
        )
        return sample.analysis_ids[:1]

    def test_01_binary_rule_negative_when_result_ge_cutoff(self):
        analysis = self._new_analysis(33.0)
        self.assertEqual(analysis.binary_interpretation, "negative")

    def test_02_binary_rule_positive_when_result_lt_cutoff(self):
        analysis = self._new_analysis(32.9)
        self.assertEqual(analysis.binary_interpretation, "positive")

    def test_03_binary_rule_disabled_returns_empty_interpretation(self):
        self.service.auto_binary_enabled = False
        analysis = self._new_analysis(20.0)
        self.assertFalse(analysis.binary_interpretation)
