# -*- coding: utf-8 -*-
"""Utilitaires bas niveau pour l'émission et la vérification des jetons JWT.

Toutes les fonctions prennent explicitement `env` en paramètre (plutôt que
de s'appuyer sur `request.env`) afin de pouvoir être appelées aussi bien
depuis un contrôleur HTTP que depuis le post_init_hook du module.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt

# Durée de vie courte pour l'access token : un jeton volé/intercepté a une
# fenêtre d'exploitation limitée. Le refresh token, plus long, évite à
# l'utilisateur mobile de se reconnecter en permanence.
ACCESS_TOKEN_TTL_MINUTES = 45
REFRESH_TOKEN_TTL_DAYS = 30

JWT_ALGORITHM = 'HS256'
_CONFIG_KEY = 'hr_ai_api.jwt_secret'


def get_jwt_secret(env):
    """Retourne la clé secrète utilisée pour signer les JWT.

    Générée une seule fois et stockée dans ir.config_parameter : elle ne
    doit JAMAIS changer entre deux redémarrages du serveur, sous peine
    d'invalider instantanément tous les jetons en circulation.
    """
    icp = env['ir.config_parameter'].sudo()
    secret = icp.get_param(_CONFIG_KEY)
    if not secret:
        secret = secrets.token_hex(32)
        icp.set_param(_CONFIG_KEY, secret)
    return secret


def encode_access_token(env, user, employee, scopes, role, must_change_password=False):
    """Construit et signe l'access token JWT pour un utilisateur ou employé authentifié."""
    now = datetime.now(timezone.utc)
    user_id = user.id if user else False
    employee_id = employee.id if employee else False

    payload = {
        'sub': str(user.id) if user else (str(employee_id) if employee_id else '0'),
        'user_id': user_id,
        'employee_id': employee_id,
        'scopes': scopes,
        'role': role,
        'must_change_password': must_change_password,
        'iat': now,
        'exp': now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, get_jwt_secret(env), algorithm=JWT_ALGORITHM)


def decode_access_token(env, token):
    """Décode et vérifie un access token. Lève jwt.ExpiredSignatureError ou
    jwt.InvalidTokenError si le jeton n'est pas valide — à charge de
    l'appelant de gérer ces exceptions."""
    return jwt.decode(token, get_jwt_secret(env), algorithms=[JWT_ALGORITHM])


def generate_refresh_token():
    """Génère un refresh token opaque (pas un JWT) : une simple chaîne
    aléatoire dont seule l'empreinte (hash) est stockée côté serveur."""
    return secrets.token_urlsafe(48)


def hash_token(raw_token):
    """Empreinte SHA-256 du refresh token, pour ne jamais stocker le jeton
    en clair en base de données (même principe qu'un mot de passe)."""
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
