# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class HrContract(models.Model):
    _inherit = 'hr.contract'

    def write(self, vals):
        result = super().write(vals)
        # 'open' = état "En cours" d'un contrat Odoo standard, c'est-à-dire
        # un contrat signé/validé et actif. On ne déclenche l'email que sur
        # cette transition précise, pas sur n'importe quelle modification.
        if vals.get('state') == 'open':
            for contract in self:
                # IMPORTANT : le candidat lié est archivé automatiquement par
                # Odoo dès qu'il est embauché (active=False). Sans
                # with_context(active_test=False), ce search() ne le trouve
                # jamais et l'email d'acceptation n'est jamais envoyé — bug
                # découvert le 25/07/2026 lors du test réel du processus.
                applicants = self.env['hr.applicant'].with_context(
                    active_test=False
                ).search([
                    ('generated_contract_id', '=', contract.id)
                ])
                for applicant in applicants:
                    applicant._send_acceptance_email()
        return result