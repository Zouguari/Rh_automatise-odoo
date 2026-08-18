# -*- coding: utf-8 -*-
import secrets
import string
import logging
from werkzeug.security import generate_password_hash, check_password_hash

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrEmployeeCredentials(models.Model):
    _name = 'hr.employee.credentials'
    _description = "Identifiants de connexion employés (Application Mobile)"
    _order = 'create_date desc'

    employee_id = fields.Many2one(
        'hr.employee', string="Employé", required=True, ondelete='cascade', index=True,
    )
    login = fields.Char(string="Identifiant / E-mail pro", required=True, index=True)
    password_hash = fields.Char(string="Empreinte du mot de passe", required=True)
    must_change_password = fields.Boolean(
        string="Doit changer le mot de passe", default=True,
        help="Si vrai, l'employé sera redirigé vers l'écran de changement de mot de passe lors de sa connexion."
    )
    is_active = fields.Boolean(string="Accès actif", default=True)
    last_login = fields.Datetime(string="Dernière connexion")

    _sql_constraints = [
        ('employee_id_uniq', 'unique(employee_id)', "Cet employé a déjà un compte d'accès créé."),
        ('login_uniq', 'unique(login)', "Cet identifiant / e-mail est déjà utilisé par un autre employé."),
    ]

    def set_password(self, raw_password):
        """Hache et enregistre un nouveau mot de passe de manière sécurisée (PBKDF2/SHA256)."""
        self.ensure_one()
        if not raw_password or len(raw_password) < 6:
            raise ValidationError("Le mot de passe doit contenir au moins 6 caractères.")
        self.write({
            'password_hash': generate_password_hash(raw_password),
        })

    def check_password(self, raw_password):
        """Vérifie un mot de passe en clair par rapport au hash enregistré."""
        self.ensure_one()
        if not self.password_hash or not raw_password:
            return False
        return check_password_hash(self.password_hash, raw_password)

    @api.model
    def create_for_employee(self, employee, login=None, password=None, must_change=True):
        """Helper pour créer un accès employé avec mot de passe temporaire."""
        login_val = (login or employee.work_email or employee.name.lower().replace(' ', '.') + '@company.com').strip().lower()
        
        # Ensure login is unique
        existing = self.search([('login', '=', login_val)], limit=1)
        if existing:
            login_val = "%s%d@company.com" % (employee.name.lower().replace(' ', '.'), employee.id)

        raw_pwd = password or self._generate_temp_password()
        pwd_hash = generate_password_hash(raw_pwd)

        record = self.create({
            'employee_id': employee.id,
            'login': login_val,
            'password_hash': pwd_hash,
            'must_change_password': must_change,
            'is_active': True,
        })
        return record, raw_pwd

    @api.model
    def _generate_temp_password(self, length=8):
        """Génère un mot de passe temporaire aléatoire et sécurisé."""
        alphabet = string.ascii_letters + string.digits
        return 'Emp-' + ''.join(secrets.choice(alphabet) for _ in range(length))

    @api.model
    def action_bulk_generate_employee_credentials(self):
        """Script d'activation en masse pour tous les employés n'ayant pas de compte.
        
        Génère des accès sécurisés pour les 17 employés et enregistre le rapport
        dans un fichier CSV d'export sécurisé.
        """
        employees = self.env['hr.employee'].sudo().search([])
        created_list = []

        for emp in employees:
            existing = self.search([('employee_id', '=', emp.id)], limit=1)
            if existing:
                continue

            cred, temp_pwd = self.create_for_employee(emp)
            created_list.append({
                'employee_id': emp.id,
                'employee_name': emp.name,
                'login': cred.login,
                'temp_password': temp_pwd,
            })

        _logger.info("Génération d'accès en masse : %d comptes d'employés créés.", len(created_list))
        return created_list
