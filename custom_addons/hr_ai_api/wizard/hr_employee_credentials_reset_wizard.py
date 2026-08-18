# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployeeCredentialsResetWizard(models.TransientModel):
    _name = 'hr.employee.credentials.reset.wizard'
    _description = "Wizard d'affichage du mot de passe temporaire réinitialisé"

    employee_id = fields.Many2one('hr.employee', string="Employé", readonly=True)
    temp_password = fields.Char(string="Mot de passe temporaire", readonly=True)
