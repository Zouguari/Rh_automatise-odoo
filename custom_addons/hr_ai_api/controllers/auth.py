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

    # NOTE : type='http' (et non 'json'). Le type 'json' d'Odoo implémente
    # le protocole JSON-RPC 2.0 (enveloppe {"jsonrpc","method","params"} en
    # entrée, {"jsonrpc","id","result"} en sortie) — inadapté à une API REST
    # consommée par une app mobile. En 'http', on lit et on écrit du JSON
    # "brut" nous-mêmes, ce qui donne une vraie API REST classique.

    @http.route('/api/v1/auth/token', type='http', auth='none', methods=['POST'], csrf=False)
    def auth_token(self, **kwargs):
        """Échange login/mot de passe contre une paire access_token / refresh_token.

        Body JSON attendu : {"login": "...", "password": "...", "device": "..."}
        """
        data = _get_json_body()
        if data is None:
            return _error(400, 'invalid_request', "Corps de requête JSON invalide.")

        login = data.get('login')
        password = data.get('password')
        device = data.get('device')

        if not login or not password:
            return _error(400, 'invalid_request', "Les paramètres 'login' et 'password' sont requis.")

        db = request.db
        try:
            uid = _authenticate(db, login, password)
        except AccessDenied:
            return _error(401, 'invalid_credentials', "Identifiants invalides.")
        except Exception:
            _logger.exception("Échec d'authentification API pour le login %s", login)
            return _error(401, 'invalid_credentials', "Identifiants invalides.")

        user = request.env['res.users'].sudo().browse(uid)
        return _issue_token_pair(user, device)

    @http.route('/api/v1/auth/refresh', type='http', auth='none', methods=['POST'], csrf=False)
    def auth_refresh(self, **kwargs):
        """Échange un refresh_token valide contre une nouvelle paire de jetons.

        Body JSON attendu : {"refresh_token": "..."}
        Le refresh token utilisé est immédiatement révoqué (rotation), pour
        limiter l'impact d'un vol de jeton.
        """
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
        return _issue_token_pair(record.user_id, record.device_info)

    @http.route('/api/v1/auth/revoke', type='http', auth='none', methods=['POST'], csrf=False)
    def auth_revoke(self, **kwargs):
        """Révoque un refresh_token (déconnexion explicite depuis le mobile).

        Body JSON attendu : {"refresh_token": "..."}
        """
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

        # Réponse identique que le jeton existe ou non, pour ne pas
        # divulguer d'information sur l'existence d'un refresh token.
        return request.make_json_response({'revoked': True})

    @http.route('/api/v1/auth/me', type='http', auth='none', methods=['GET'], csrf=False)
    @require_auth()
    def auth_me(self, **kwargs):
        """Retourne le profil de l'utilisateur authentifié par l'access token."""
        payload = request.jwt_payload
        user = request.env['res.users'].sudo().browse(payload['sub'])
        employee = None
        if payload.get('employee_id'):
            employee = request.env['hr.employee'].sudo().browse(payload['employee_id'])

        return request.make_json_response({
            'user_id': user.id,
            'name': user.name,
            'login': user.login,
            'employee_id': employee.id if employee else None,
            'employee_name': employee.name if employee else None,
            'role': payload.get('role'),
            'scopes': payload.get('scopes'),
        })


def _authenticate(db, login, password):
    """Authentifie un utilisateur Odoo et retourne son uid.

    La signature de res.users.authenticate() a changé entre versions/
    correctifs d'Odoo 17 : certains builds attendent
    (db, login, password, user_agent_env) [confirmé par nos tests], d'autres
    (db, credential_dict, user_agent_env). On essaie la première (la plus
    répandue), puis on retombe sur la seconde si elle échoue par TypeError.
    """
    Users = request.env['res.users']
    user_agent_env = {'interactive': False}
    try:
        return Users.authenticate(db, login, password, user_agent_env)
    except TypeError:
        credential = {'login': login, 'password': password, 'type': 'password'}
        auth_info = Users.authenticate(db, credential, user_agent_env)
        return auth_info['uid']


def _get_json_body():
    """Parse le corps de la requête HTTP comme du JSON brut.

    Retourne un dict, {} si le corps est vide, ou None si le JSON est
    invalide (à charge de l'appelant de renvoyer une erreur 400).
    """
    raw = request.httprequest.get_data()
    if not raw:
        return {}
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None


def _issue_token_pair(user, device=None):
    """Construit et enregistre une nouvelle paire access_token/refresh_token
    pour l'utilisateur donné. Factorisé car utilisé par /auth/token ET
    /auth/refresh (rotation)."""
    employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
    role = role_for_user(user)
    scopes = scopes_for_role(role)

    access_token = encode_access_token(request.env, user, employee, scopes, role)
    refresh_raw = generate_refresh_token()

    request.env['api.auth.token'].sudo().create({
        'user_id': user.id,
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
    })


def _error(status, code, message):
    return request.make_json_response({'error': code, 'message': message}, status=status)
