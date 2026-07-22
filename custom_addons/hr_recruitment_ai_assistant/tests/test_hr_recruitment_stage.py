# -*- coding: utf-8 -*-
import os
import sys
import unittest
from unittest.mock import MagicMock

try:
    from odoo.tests.common import TransactionCase, tagged
    HAS_ODOO = True
except (ImportError, AttributeError):
    HAS_ODOO = False
    TransactionCase = unittest.TestCase
    def tagged(*args, **kwargs):
        return lambda cls: cls

# Import hooks de manière sécurisée (compatible hors-Odoo et dans Odoo)
try:
    from custom_addons.hr_recruitment_ai_assistant.hooks import _mark_default_interview_stages
except (ImportError, AttributeError):
    import importlib.util
    hooks_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'hooks.py'))
    spec = importlib.util.spec_from_file_location("hooks_module", hooks_path)
    hooks_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hooks_module)
    _mark_default_interview_stages = hooks_module._mark_default_interview_stages


@tagged('post_install', '-at_install')
class TestHrRecruitmentStage(TransactionCase):
    """Tests unitaires Odoo pour la personnalisation des étapes de recrutement RH & IA."""

    def setUp(self):
        super(TestHrRecruitmentStage, self).setUp()
        if HAS_ODOO and hasattr(self, 'env'):
            self.stage_model = self.env['hr.recruitment.stage']

    def test_stage_interview_type_fields(self):
        """Vérifie la création et la mise à jour des champs interview_type et is_interview_stage."""
        if not HAS_ODOO or not hasattr(self, 'env'):
            self.skipTest("Environnement Odoo non actif - test d'intégration ignoré en standalone.")

        stage_rh = self.stage_model.create({
            'name': 'Entretien RH Test',
            'is_interview_stage': True,
            'interview_type': 'rh',
        })
        self.assertTrue(stage_rh.is_interview_stage)
        self.assertEqual(stage_rh.interview_type, 'rh')

        stage_tech = self.stage_model.create({
            'name': 'Entretien Technique Test',
            'is_interview_stage': True,
            'interview_type': 'technique',
        })
        self.assertTrue(stage_tech.is_interview_stage)
        self.assertEqual(stage_tech.interview_type, 'technique')

    def test_post_init_hook_mark_default_interview_stages(self):
        """Vérifie que le hook _mark_default_interview_stages renomme et configure les étapes d'entretien."""
        if not HAS_ODOO or not hasattr(self, 'env'):
            self.skipTest("Environnement Odoo non actif - test d'intégration ignoré en standalone.")

        stage_first = self.stage_model.create({
            'name': 'First Interview',
            'is_interview_stage': False,
        })
        stage_second = self.stage_model.create({
            'name': 'Second Interview',
            'is_interview_stage': False,
        })

        _mark_default_interview_stages(self.env)

        stage_first.invalidate_recordset()
        stage_second.invalidate_recordset()

        self.assertEqual(stage_first.name, 'Entretien RH')
        self.assertTrue(stage_first.is_interview_stage)
        self.assertEqual(stage_first.interview_type, 'rh')

        self.assertEqual(stage_second.name, 'Entretien Technique')
        self.assertTrue(stage_second.is_interview_stage)
        self.assertEqual(stage_second.interview_type, 'technique')


class TestHrRecruitmentStageHookMock(unittest.TestCase):
    """Test unitaire standalone (Mock) pour valider le hook _mark_default_interview_stages."""

    def test_mark_default_interview_stages_mock(self):
        mock_env = MagicMock()
        mock_rh_stage = MagicMock()
        mock_tech_stage = MagicMock()

        def search_side_effect(domain):
            if domain == [('name', 'in', ['First Interview', 'Premier entretien'])]:
                return mock_rh_stage
            elif domain == [('name', 'in', ['Second Interview', 'Second entretien', 'Deuxième entretien'])]:
                return mock_tech_stage
            return MagicMock(__len__=lambda self: 0)

        mock_env['hr.recruitment.stage'].search.side_effect = search_side_effect

        _mark_default_interview_stages(mock_env)

        mock_rh_stage.write.assert_called_once_with({
            'name': 'Entretien RH',
            'is_interview_stage': True,
            'interview_type': 'rh',
        })
        mock_tech_stage.write.assert_called_once_with({
            'name': 'Entretien Technique',
            'is_interview_stage': True,
            'interview_type': 'technique',
        })


if __name__ == '__main__':
    unittest.main()
