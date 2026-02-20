from odoo import fields
from odoo.tests.common import TransactionCase


class TestPersonnelCompetency(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base_group = cls.env.ref("base.group_user")
        reviewer_group = cls.env.ref("laboratory_management.group_lab_reviewer")
        manager_group = cls.env.ref("laboratory_management.group_lab_manager")

        cls.user_analyst = cls.env["res.users"].create(
            {
                "name": "Matrix Analyst",
                "login": "matrix_analyst",
                "email": "matrix_analyst@example.com",
                "group_ids": [(6, 0, [base_group.id])],
            }
        )
        cls.user_reviewer = cls.env["res.users"].create(
            {
                "name": "Matrix Reviewer",
                "login": "matrix_reviewer",
                "email": "matrix_reviewer@example.com",
                "group_ids": [(6, 0, [reviewer_group.id])],
            }
        )
        cls.user_manager = cls.env["res.users"].create(
            {
                "name": "Matrix Manager",
                "login": "matrix_manager",
                "email": "matrix_manager@example.com",
                "group_ids": [(6, 0, [manager_group.id])],
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Matrix Patient"})
        cls.service = cls.env["lab.service"].create(
            {
                "name": "Matrix Service",
                "code": "MATRIX-SVC",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "list_price": 100,
            }
        )

    def test_01_training_generate_authorizations(self):
        program = self.env["lab.quality.program"].create(
            {
                "year": fields.Date.today().year,
                "objective": "Competency plan",
                "owner_id": self.env.user.id,
            }
        )
        training = self.env["lab.quality.training"].create(
            {
                "program_id": program.id,
                "topic": "PCR competency",
                "training_date": fields.Date.today(),
                "authorization_role": "analyst",
                "authorization_service_ids": [(6, 0, [self.service.id])],
                "attendee_ids": [
                    (0, 0, {"user_id": self.user_analyst.id, "attended": True, "score": 88}),
                    (0, 0, {"user_id": self.user_reviewer.id, "attended": True, "score": 40}),
                ],
            }
        )
        training.action_done()
        training.action_generate_service_authorizations()
        auths = self.env["lab.service.authorization"].search(
            [
                ("user_id", "=", self.user_analyst.id),
                ("service_id", "=", self.service.id),
                ("role", "=", "analyst"),
            ]
        )
        self.assertEqual(len(auths), 1)
        self.assertEqual(auths.state, "pending")

        # idempotent for already-generated combinations
        training.action_generate_service_authorizations()
        auths2 = self.env["lab.service.authorization"].search(
            [
                ("user_id", "=", self.user_analyst.id),
                ("service_id", "=", self.service.id),
                ("role", "=", "analyst"),
            ]
        )
        self.assertEqual(len(auths2), 1)

    def test_02_personnel_matrix_detects_gap_and_ok(self):
        sample = self.env["lab.sample"].create(
            {
                "patient_id": self.partner.id,
                "state": "verified",
                "verified_date": fields.Datetime.now(),
                "technical_reviewer_id": self.user_reviewer.id,
                "medical_reviewer_id": self.user_manager.id,
                "analysis_ids": [
                    (
                        0,
                        0,
                        {
                            "service_id": self.service.id,
                            "state": "verified",
                            "result_value": "1.0",
                            "analyst_id": self.user_analyst.id,
                        },
                    )
                ],
            }
        )
        self.assertTrue(sample)

        run = self.env["lab.personnel.matrix.run"].create(
            {
                "period_days": 30,
                "service_ids": [(6, 0, [self.service.id])],
                "include_analyst": True,
                "include_technical_reviewer": True,
                "include_medical_reviewer": True,
            }
        )
        run.action_generate_lines()
        self.assertGreater(run.gap_lines, 0)

        auth_obj = self.env["lab.service.authorization"]
        for user_id, role in [
            (self.user_analyst.id, "analyst"),
            (self.user_reviewer.id, "technical_reviewer"),
            (self.user_manager.id, "medical_reviewer"),
        ]:
            auth_obj.create(
                {
                    "user_id": user_id,
                    "service_id": self.service.id,
                    "role": role,
                    "state": "approved",
                    "effective_from": fields.Date.today(),
                    "effective_to": fields.Date.add(fields.Date.today(), months=12),
                }
            )

        run2 = self.env["lab.personnel.matrix.run"].create(
            {
                "period_days": 30,
                "service_ids": [(6, 0, [self.service.id])],
                "include_analyst": True,
                "include_technical_reviewer": True,
                "include_medical_reviewer": True,
            }
        )
        run2.action_generate_lines()
        self.assertEqual(run2.gap_lines, 0)
        self.assertGreater(run2.authorized_lines, 0)
