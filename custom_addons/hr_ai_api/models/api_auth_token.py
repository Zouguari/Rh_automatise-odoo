# -*- coding: utf-8 -*-
from odoo import fields, models


class ApiAuthToken(models.Model):
    _name = 'api.auth.token'
    _description = "Jeton de rafraîchissement API (application mobile)"
    _order = 'create_date desc'

    user_id = fields.Many2one(
        'res.users', string="Utilisateur", required=False, index=True,
        ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee', string="Employé", required=False, index=True,
        ondelete='cascade',
    )
    token_hash = fields.Char(
        string="Empreinte du refresh token", required=True, index=True,
        help="SHA-256 du refresh token. Le jeton en clair n'est jamais "
             "stocké, exactement comme un mot de passe.",
    )
    scope = fields.Char(string="Scopes accordés")
    device_info = fields.Char(string="Appareil / contexte")
    expires_at = fields.Datetime(string="Expire le", required=True)
    revoked = fields.Boolean(string="Révoqué", default=False)

    def _is_valid(self):
        self.ensure_one()
        return not self.revoked and self.expires_at and self.expires_at > fields.Datetime.now()
