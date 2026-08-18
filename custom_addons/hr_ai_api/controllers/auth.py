# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import AccessDenied
from odoo.http import request

from ..utils.auth_decorator import require_auth
from ..utils.jwt_helper import (
    ACCESS_TOKEN_TTL_MINUTES,
    REFRESH_TOKEN_TTL_DAYS,
    encode_access_token,
    generate_refresh_token,
    hash_token,
)
from ..utils.roles import role_for_user, scopes_for_role

_logger = logging.getLogger(__name__)


class HrAiApiAuthController(http.Controller):

    @http.route('/api/v1/auth/token', type='http', auth='none', methods=['POST'], csrf=False)
    def auth_token(self, **kwargs):
        """Échange login/mot de passe contre une paire access_token / refresh_token.

        Accepte à la fois :
        1. Les identifiants custom hr.employee.credentials (découplés de res.users)
        2. Le fallback Odoo res.users (pour les RH / managers d'origine)
        """
        data = _get_json_body()
        if data is None:
            return _error(400, 'invalid_request', "Corps de requête JSON invalide.")

        login_raw = data.get('login')
        password = data.get('password')
        device = data.get('device')

        if not login_raw or not password:
            return _error(400, 'invalid_request', "Les paramètres 'login' et 'password' sont requis.")

        login = login_raw.strip().lower()
        db = request.db

        # 1. Vérification prioritaire dans hr.employee.credentials (découplé de res.users)
        cred = request.env['hr.employee.credentials'].sudo().search([('login', '=', login)], limit=1)
        if not cred:
            # Essayer de chercher par e-mail pro de l'employé
            emp = request.env['hr.employee'].sudo().search([('work_email', '=ilike', login)], limit=1)
            if emp:
                cred = request.env['hr.employee.credentials'].sudo().search([('employee_id', '=', emp.id)], limit=1)

        if cred:
            if not cred.is_active:
                return _error(401, 'account_disabled', "Ce compte d'accès est désactivé. Veuillez contacter le RH.")

            if cred.check_password(password):
                cred.sudo().write({'last_login': fields.Datetime.now()})
                employee = cred.employee_id
                user = employee.user_id if employee.user_id else None
                return _issue_token_pair_for_employee(employee, user=user, cred=cred, device=device)

        # 2. Fallback Odoo classique (res.users) pour admin/demo/managers
        try:
            uid = _authenticate(db, login_raw, password)
            user = request.env['res.users'].sudo().browse(uid)
            employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            return _issue_token_pair_for_employee(employee, user=user, cred=None, device=device)
        except AccessDenied:
            return _error(401, 'invalid_credentials', "Identifiants invalides.")
        except Exception as exc:
            _logger.exception("Échec d'authentification API pour %s: %s", login_raw, str(exc))
            return _error(401, 'invalid_credentials', "Identifiants invalides.")

    @http.route('/api/v1/auth/refresh', type='http', auth='none', methods=['POST'], csrf=False)
    def auth_refresh(self, **kwargs):
        """Échange un refresh_token valide contre une nouvelle paire de jetons."""
        data = _get_json_body()
        if data is None:
            return _error(400, 'invalid_request', "Corps de requête JSON invalide.")

        raw_refresh = data.get('refresh_token')
        if not raw_refresh:
            return _error(400, 'invalid_request', "Le paramètre 'refresh_token' est requis.")

        token_hash = hash_token(raw_refresh)
        record = request.env['api.auth.token'].sudo().search(
            [('token_hash', '=', token_hash)], limit=1
        )

        if not record or not record._is_valid():
            return _error(401, 'invalid_grant', "Refresh token invalide, expiré ou révoqué.")

        record.revoked = True

        employee = record.employee_id or (
            request.env['hr.employee'].sudo().search([('user_id', '=', record.user_id.id)], limit=1)
            if record.user_id else None
        )
        user = record.user_id or (employee.user_id if employee else None)
        cred = request.env['hr.employee.credentials'].sudo().search([('employee_id', '=', employee.id)], limit=1) if employee else None

        return _issue_token_pair_for_employee(employee, user=user, cred=cred, device=record.device_info)

    @http.route('/api/v1/auth/revoke', type='http', auth='none', methods=['POST'], csrf=False)
    def auth_revoke(self, **kwargs):
        """Révoque un refresh_token (déconnexion explicite depuis le mobile)."""
        data = _get_json_body()
        if data is None:
            return _error(400, 'invalid_request', "Corps de requête JSON invalide.")

        raw_refresh = data.get('refresh_token')
        if not raw_refresh:
            return _error(400, 'invalid_request', "Le paramètre 'refresh_token' est requis.")

        token_hash = hash_token(raw_refresh)
        record = request.env['api.auth.token'].sudo().search(
            [('token_hash', '=', token_hash)], limit=1
        )
        if record:
            record.revoked = True

        return request.make_json_response({'revoked': True})

    @http.route('/api/v1/auth/me', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth()
    def auth_me(self, **kwargs):
        """Retourne le profil de l'utilisateur ou employé authentifié par l'access token."""
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')
        user_id = payload.get('user_id')

        employee = request.env['hr.employee'].sudo().browse(employee_id) if employee_id else None
        user = request.env['res.users'].sudo().browse(user_id) if user_id else None

        must_change = payload.get('must_change_password', False)
        if employee:
            cred = request.env['hr.employee.credentials'].sudo().search([('employee_id', '=', employee.id)], limit=1)
            if cred:
                must_change = cred.must_change_password

        return request.make_json_response({
            'user_id': user.id if user else None,
            'name': employee.name if employee else (user.name if user else "Employé"),
            'login': user.login if user else (employee.work_email or employee.name),
            'employee_id': employee.id if employee else None,
            'employee_name': employee.name if employee else None,
            'role': payload.get('role', 'employee'),
            'scopes': payload.get('scopes', []),
            'must_change_password': must_change,
        })

    @http.route('/api/v1/auth/change-password', type='http', auth='none', methods=['POST'], csrf=False)
    @require_auth()
    def change_password(self, **kwargs):
        """Endpoint de modification obligatoire/volontaire du mot de passe."""
        payload = request.jwt_payload
        employee_id = payload.get('employee_id')
        user_id = payload.get('user_id')

        data = _get_json_body()
        if data is None:
            return _error(400, 'invalid_request', "Corps JSON invalide.")

        old_password = data.get('old_password') or data.get('current_password')
        new_password = data.get('new_password')

        if not new_password or len(new_password) < 6:
            return _error(400, 'weak_password', "Le nouveau mot de passe doit contenir au moins 6 caractères.")

        # 1. Si compte hr.employee.credentials
        if employee_id:
            cred = request.env['hr.employee.credentials'].sudo().search([('employee_id', '=', employee_id)], limit=1)
            if cred:
                # Si must_change_password est True, on permet le changement direct (avec ou sans l'ancien mot de passe)
                if not cred.must_change_password and old_password:
                    if not cred.check_password(old_password):
                        return _error(401, 'invalid_old_password', "Ancien mot de passe incorrect.")

                cred.set_password(new_password)
                cred.sudo().write({'must_change_password': False})
                return request.make_json_response({
                    'success': True,
                    'message': "Mot de passe modifié avec succès.",
                    'must_change_password': False,
                })

        # 2. Si compte res.users
        if user_id:
            user = request.env['res.users'].sudo().browse(user_id)
            if user:
                user.sudo().write({'password': new_password})
                return request.make_json_response({
                    'success': True,
                    'message': "Mot de passe modifié avec succès.",
                    'must_change_password': False,
                })

        return _error(400, 'account_not_found', "Compte introuvable.")


def _authenticate(db, login, password):
    Users = request.env['res.users']
    user_agent_env = {'interactive': False}
    try:
        return Users.authenticate(db, login, password, user_agent_env)
    except TypeError:
        credential = {'login': login, 'password': password, 'type': 'password'}
        auth_info = Users.authenticate(db, credential, user_agent_env)
        return auth_info['uid']


def _get_json_body():
    raw = request.httprequest.get_data()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None


def _issue_token_pair_for_employee(employee, user=None, cred=None, device=None):
    must_change = cred.must_change_password if cred else False

    if user:
        role = role_for_user(user)
    else:
        role = 'employee'

    scopes = scopes_for_role(role)

    access_token = encode_access_token(
        request.env, user, employee, scopes, role, must_change_password=must_change
    )
    refresh_raw = generate_refresh_token()

    request.env['api.auth.token'].sudo().create({
        'user_id': user.id if user else False,
        'employee_id': employee.id if employee else False,
        'token_hash': hash_token(refresh_raw),
        'scope': ' '.join(scopes),
        'device_info': device or '',
        'expires_at': fields.Datetime.now() + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
    })

    return request.make_json_response({
        'access_token': access_token,
        'refresh_token': refresh_raw,
        'token_type': 'Bearer',
        'expires_in': ACCESS_TOKEN_TTL_MINUTES * 60,
        'scope': ' '.join(scopes),
        'must_change_password': must_change,
    })


def _error(status, code, message):
    return request.make_json_response({'error': code, 'message': message}, status=status)
