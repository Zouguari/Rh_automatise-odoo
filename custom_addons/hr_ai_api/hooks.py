# -*- coding: utf-8 -*-
from .utils.jwt_helper import get_jwt_secret


def post_init_hook(env):
    """Pré-génère la clé secrète JWT dès l'installation du module, et crée automatiquement
    les identifiants d'accès mobiles pour tous les employés existants."""
    get_jwt_secret(env)
    try:
        env['hr.employee.credentials'].sudo().action_bulk_generate_employee_credentials()
    except Exception as e:
        pass

