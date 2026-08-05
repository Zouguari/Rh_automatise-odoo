# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _ai_attendance_score(self, days=90):
        """Score de ponctualité sur 0-100 (100 = jamais en retard), calculé
        sur les `days` derniers jours. Renvoie None si aucune donnée de
        présence n'est disponible sur la période (plutôt que de fausser la
        moyenne avec un score par défaut)."""
        self.ensure_one()
        since = fields.Datetime.now() - timedelta(days=days)
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', self.id),
            ('check_in', '>=', since),
        ])
        total = len(attendances)
        if not total:
            return None

        late_count = len(attendances.filtered('is_late'))
        late_ratio = late_count / total
        return round(100 * (1 - late_ratio), 1)

    def _ai_skills_score(self):
        """Score de couverture des compétences requises par le poste actuel,
        sur 0-100 (100 = toutes les compétences requises sont au niveau
        attendu). Renvoie None si aucune compétence n'est définie pour le
        poste (rien à évaluer)."""
        self.ensure_one()
        analysis = self.get_skill_gap_analysis()

        matched = len(analysis['matched_skills'])
        missing = len(analysis['missing_skills'])
        underleveled = len(analysis['underleveled_skills'])
        total = matched + missing + underleveled
        if not total:
            return None

        return round(100 * matched / total, 1)
