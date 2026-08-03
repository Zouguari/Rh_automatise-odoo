# -*- coding: utf-8 -*-
"""Décorateur à poser sur toute route API qui doit être protégée par un
access token JWT (c'est-à-dire toutes les routes sauf /auth/token,
/auth/refresh et /auth/revoke).

Usage :
    @http.route('/api/v1/employees/<int:employee_id>', type='json', auth='none', ...)
    @require_auth(['profile:read'])
    def get_employee(self, employee_id, **kwargs):
        payload = request.jwt_payload  # {'sub', 'employee_id', 'role', 'scopes', ...}
        ...
"""
import logging
from functools import wraps

import jwt

from odoo.http import request

from .jwt_helper import decode_access_token, get_jwt_secret

_logger = logging.getLogger(__name__)


def require_auth(scopes=None):
    required_scopes = scopes or []

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.httprequest.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return request.make_json_response(
                    {
                        'error': 'unauthorized',
                        'message': "En-tête 'Authorization: Bearer <token>' manquant.",
                    },
                    status=401,
                )

            token = auth_header.split(' ', 1)[1].strip()
            try:
                payload = decode_access_token(request.env, token)
            except jwt.ExpiredSignatureError:
                return request.make_json_response(
                    {
                        'error': 'token_expired',
                        'message': "Le jeton d'accès a expiré, utilisez /api/v1/auth/refresh.",
                    },
                    status=401,
                )
            except jwt.InvalidTokenError as exc:
                # NOTE DEBUG : log volontairement verbeux le temps de
                # diagnostiquer un souci de vérification de signature.
                secret_preview = get_jwt_secret(request.env)[:8]
                _logger.warning(
                    "Échec de décodage JWT (%s: %s) — token reçu (30 premiers "
                    "caractères) : %r ; longueur totale : %d ; secret utilisé "
                    "(8 premiers caractères) : %s ; base de données : %s",
                    type(exc).__name__, exc, token[:30], len(token),
                    secret_preview, request.env.cr.dbname,
                )
                return request.make_json_response(
                    {'error': 'invalid_token', 'message': "Jeton d'accès invalide."},
                    status=401,
                )

            granted_scopes = set(payload.get('scopes', []))
            has_required_scope = (
                not required_scopes
                or granted_scopes.intersection(required_scopes)
                or 'admin:*' in granted_scopes
            )
            if not has_required_scope:
                return request.make_json_response(
                    {
                        'error': 'insufficient_scope',
                        'message': "Permissions insuffisantes pour cette action.",
                    },
                    status=403,
                )

            # Rendu disponible à la route protégée sans avoir à re-décoder le jeton.
            request.jwt_payload = payload
            return fn(*args, **kwargs)

        return wrapper

    return decorator
