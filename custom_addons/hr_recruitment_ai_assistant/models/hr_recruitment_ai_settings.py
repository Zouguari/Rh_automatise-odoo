# -*- coding: utf-8 -*-
import logging
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

from .hr_applicant import GEMINI_URL

_logger = logging.getLogger(__name__)

_CONFIG_PARAM = 'smart_hr_ai.gemini_api_key'


class HrRecruitmentAiSettings(models.TransientModel):
    _name = 'hr.recruitment.ai.settings'
    _description = "Configuration de l'Assistant RH IA"

    gemini_api_key = fields.Char(
        string="Clé API Gemini",
        help="Clé obtenue sur Google AI Studio (ai.google.dev). Ne partage "
             "jamais cette clé et ne la commite jamais sur GitHub."
    )
    auto_run_pipeline_on_create = fields.Boolean(
        string="Analyser automatiquement les nouvelles candidatures",
        help="Si coché : les candidatures arrivant par le portail carrière "
             "web ou par email (alias entrant) sont analysées automatiquement "
             "par l'IA (extraction, score, questions d'entretien) sans "
             "action du recruteur, via une tâche planifiée qui repasse "
             "toutes les 15 minutes. Décoche si tu préfères garder un "
             "contrôle manuel (bouton Pipeline IA complet) sur chaque "
             "candidat, par exemple pour maîtriser la consommation de "
             "quota IA."
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        config = self.env['ir.config_parameter'].sudo()
        if 'gemini_api_key' in fields_list:
            res['gemini_api_key'] = config.get_param(_CONFIG_PARAM, default='')
        if 'auto_run_pipeline_on_create' in fields_list:
            res['auto_run_pipeline_on_create'] = config.get_param(
                'smart_hr_ai.auto_run_pipeline_on_create', default='1'
            ) == '1'
        return res

    def action_save(self):
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        config.set_param(_CONFIG_PARAM, self.gemini_api_key or '')
        config.set_param(
            'smart_hr_ai.auto_run_pipeline_on_create',
            '1' if self.auto_run_pipeline_on_create else '0'
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Configuration enregistrée",
                'message': "La clé API Gemini a été mise à jour.",
                'type': 'success',
                'sticky': False,
            },
        }

    def action_test_connection(self):
        """Fait un tout petit appel Gemini (pas d'extraction de CV) juste
        pour vérifier que la clé fonctionne, sans consommer de quota inutile."""
        self.ensure_one()
        if not self.gemini_api_key:
            raise UserError("Renseigne d'abord une clé API avant de tester.")

        payload = {
            "contents": [{"parts": [{"text": "Réponds uniquement le mot OK."}]}],
            "generationConfig": {"maxOutputTokens": 10, "thinkingConfig": {"thinkingBudget": 0}},
        }
        try:
            response = requests.post(
                f"{GEMINI_URL}?key={self.gemini_api_key}", json=payload, timeout=15,
            )
        except requests.exceptions.RequestException as e:
            raise UserError(f"Impossible de contacter l'API Gemini (problème réseau) : {e}")

        if response.status_code == 200:
            message, msg_type = "✅ Connexion réussie, la clé API fonctionne.", "success"
        elif response.status_code in (401, 403):
            message, msg_type = "❌ Clé API refusée (invalide ou révoquée).", "danger"
        elif response.status_code == 429:
            message, msg_type = (
                "⚠️ Clé valide, mais quota déjà atteint pour l'instant.", "warning"
            )
        else:
            message, msg_type = (
                f"❌ Erreur inattendue (HTTP {response.status_code}) : "
                f"{response.text[:200]}", "danger"
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Test de connexion Gemini",
                'message': message,
                'type': msg_type,
                'sticky': True,
            },
        }
        