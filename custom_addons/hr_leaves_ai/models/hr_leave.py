# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    ai_recommendation = fields.Selection(
        [
            ('approve', "Approuver"),
            ('caution', "Vigilance"),
            ('refuse', "Refuser"),
        ],
        string="Recommandation IA", readonly=True, copy=False,
    )
    ai_justification = fields.Text(string="Justification IA", readonly=True, copy=False)
    ai_conflict_count = fields.Integer(string="Conflits d'équipe détectés", readonly=True, copy=False)
    ai_computed_on = fields.Datetime(string="Analysée le", readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)
        leaves.action_compute_ai_recommendation()
        return leaves

    def action_compute_ai_recommendation(self):
        """Calcule (ou recalcule) la recommandation IA pour chaque demande.
        Déclenché automatiquement à la création, et rejouable manuellement
        (bouton dans la vue, ou endpoint API dédié plus tard)."""
        for leave in self:
            conflict_count = leave._ai_get_team_conflict_count()
            recommendation, justification = leave._ai_build_recommendation(conflict_count)
            leave.write({
                'ai_recommendation': recommendation,
                'ai_justification': justification,
                'ai_conflict_count': conflict_count,
                'ai_computed_on': fields.Datetime.now(),
            })
            self.env['hr.leave.ai.recommendation'].sudo().create({
                'leave_id': leave.id,
                'recommendation': recommendation,
                'justification': justification,
                'conflict_count': conflict_count,
            })
        return True

    def _ai_get_team_conflict_count(self):
        """Nombre de collègues du même département déjà en congé confirmé/
        validé sur une période qui chevauche celle de la demande."""
        self.ensure_one()
        if not self.department_id or not self.date_from or not self.date_to:
            return 0
        domain = [
            ('id', '!=', self.id),
            ('department_id', '=', self.department_id.id),
            ('state', 'in', ('confirm', 'validate1', 'validate')),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ]
        return self.env['hr.leave'].sudo().search_count(domain)

    def _ai_build_recommendation(self, conflict_count):
        """Logique de recommandation : heuristique simple à base de règles
        pour cette première itération (solde de congés + conflits d'équipe).
        Pourra être remplacée/enrichie par un modèle IA sans changer les
        champs ni les endpoints qui les exposent."""
        self.ensure_one()

        conflict_threshold = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'hr_leaves_ai.conflict_threshold', default=2
            )
        )

        remaining = self.employee_id.remaining_leaves
        requested_days = self.number_of_days

        if remaining is not None and requested_days > remaining:
            return 'refuse', (
                "Solde de congés insuffisant : %.1f jour(s) demandé(s) pour "
                "%.1f jour(s) restant(s)." % (requested_days, remaining)
            )

        if conflict_count >= conflict_threshold:
            return 'caution', (
                "%d collègue(s) du même département sont déjà absent(s) sur "
                "une période chevauchante. Vérifier la charge d'équipe avant "
                "validation." % conflict_count
            )

        return 'approve', (
            "Solde suffisant et aucun conflit de planning détecté dans "
            "l'équipe : la demande peut être validée."
        )
