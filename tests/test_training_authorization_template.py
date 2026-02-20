from odoo import fields
from odoo.tests.common import TransactionCase


class TestTrainingAuthorizationTemplate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env["lab.quality.program"].create(
            {
                "year": fields.Date.today().year,
                "objective": "Template-driven competency",
                "owner_id": cls.env.user.id,
            }
        )
        cls.service = cls.env["lab.service"].create(
            {
                "name": "TPL Service",
                "code": "TPL-SVC",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "list_price": 10,
            }
        )

    def test_01_apply_template_to_training(self):
        template = self.env["lab.training.authorization.template"].create(
            {
                "name": "PCR Analyst Template",
                "code": "TPL-AN-01",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 10,
                            "role": "analyst",
                            "service_ids": [(6, 0, [self.service.id])],
                            "effective_months": 18,
                        },
                    )
                ],
            }
        )
        training = self.env["lab.quality.training"].create(
            {
                "program_id": self.program.id,
                "topic": "Template Test",
                "authorization_template_id": template.id,
            }
        )
        training.action_apply_authorization_template()
        self.assertEqual(training.authorization_role, "analyst")
        self.assertEqual(training.authorization_effective_months, 18)
        self.assertEqual(training.authorization_service_ids, self.service)

    def test_02_generate_authorizations_from_multi_line_template(self):
        template = self.env["lab.training.authorization.template"].create(
            {
                "name": "Multi Role Template",
                "code": "TPL-MULTI-01",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 10,
                            "role": "analyst",
                            "service_ids": [(6, 0, [self.service.id])],
                            "effective_months": 12,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 20,
                            "role": "technical_reviewer",
                            "service_ids": [(6, 0, [self.service.id])],
                            "effective_months": 6,
                        },
                    ),
                ],
            }
        )
        training = self.env["lab.quality.training"].create(
            {
                "program_id": self.program.id,
                "topic": "Template Multi Generate",
                "authorization_template_id": template.id,
                "attendee_ids": [
                    (0, 0, {"user_id": self.env.user.id, "attended": True, "score": 90}),
                ],
            }
        )
        training.action_done()
        auth_obj = self.env["lab.service.authorization"]
        before_analyst = auth_obj.search_count(
            [("user_id", "=", self.env.user.id), ("service_id", "=", self.service.id), ("role", "=", "analyst")]
        )
        before_tech = auth_obj.search_count(
            [
                ("user_id", "=", self.env.user.id),
                ("service_id", "=", self.service.id),
                ("role", "=", "technical_reviewer"),
            ]
        )
        training.action_generate_service_authorizations()
        after_analyst = auth_obj.search_count(
            [("user_id", "=", self.env.user.id), ("service_id", "=", self.service.id), ("role", "=", "analyst")]
        )
        after_tech = auth_obj.search_count(
            [
                ("user_id", "=", self.env.user.id),
                ("service_id", "=", self.service.id),
                ("role", "=", "technical_reviewer"),
            ]
        )
        self.assertGreater(after_analyst, before_analyst)
        self.assertGreater(after_tech, before_tech)

    def test_03_split_plan_generates_child_trainings(self):
        template = self.env["lab.training.authorization.template"].create(
            {
                "name": "Split Plan Template",
                "code": "TPL-SPLIT-01",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": 10,
                            "role": "analyst",
                            "service_ids": [(6, 0, [self.service.id])],
                            "effective_months": 12,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "sequence": 20,
                            "role": "medical_reviewer",
                            "service_ids": [(6, 0, [self.service.id])],
                            "effective_months": 12,
                        },
                    ),
                ],
            }
        )
        training = self.env["lab.quality.training"].create(
            {
                "program_id": self.program.id,
                "topic": "Split Base",
                "authorization_template_id": template.id,
                "training_date": fields.Date.today(),
            }
        )
        training.action_split_training_plan()
        self.assertEqual(training.child_training_count, 2)
        self.assertEqual(set(training.child_training_ids.mapped("state")), {"scheduled"})

    def test_04_upcoming_training_cron_marks_and_creates_activity(self):
        training = self.env["lab.quality.training"].create(
            {
                "program_id": self.program.id,
                "topic": "Upcoming Reminder",
                "training_date": fields.Date.add(fields.Date.today(), days=1),
                "state": "scheduled",
                "attendee_ids": [
                    (0, 0, {"user_id": self.env.user.id, "attended": False, "score": 0}),
                ],
            }
        )
        self.env["lab.quality.program.reminder.mixin"]._cron_notify_upcoming_trainings()
        training.flush_recordset(["schedule_reminder_sent"])
        self.assertTrue(training.schedule_reminder_sent)

    def test_05_auto_reschedule_conflict(self):
        base_date = fields.Date.today()
        t1 = self.env["lab.quality.training"].create(
            {
                "program_id": self.program.id,
                "topic": "Conflict A",
                "training_date": base_date,
                "trainer_id": self.env.user.id,
                "state": "scheduled",
            }
        )
        t2 = self.env["lab.quality.training"].create(
            {
                "program_id": self.program.id,
                "topic": "Conflict B",
                "training_date": base_date,
                "trainer_id": self.env.user.id,
                "state": "scheduled",
            }
        )
        self.assertTrue(t1.schedule_conflict or t2.schedule_conflict)
        t2.action_auto_reschedule_conflicts()
        self.assertNotEqual(t2.training_date, base_date)
