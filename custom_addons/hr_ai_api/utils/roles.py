# -*- coding: utf-8 -*-
"""Détermination du rôle fonctionnel et des scopes API à partir des
groupes de sécurité Odoo de l'utilisateur.

Centraliser cette logique ici évite de la dupliquer dans chaque
contrôleur, et permet de l'ajuster facilement au fur et à mesure que de
nouveaux modules (congés, présences, ...) ajoutent leurs propres scopes.
"""

BASE_SCOPES = [
    'profile:read',
    'leaves:read', 'leaves:write',
    'attendance:read', 'attendance:write',
    'skills:read',
    'appraisals:read',
]

MANAGER_EXTRA_SCOPES = [
    'leaves:approve',
    'attendance:team_read',
    'appraisals:write',
]

RH_EXTRA_SCOPES = [
    'employees:write',
    'analytics:read',
    'admin:*',  # scope joker : accès à toutes les routes protégées par scope
]


def role_for_user(user):
    """Retourne 'rh', 'manager' ou 'employee' selon les groupes Odoo."""
    if user.has_group('hr.group_hr_manager'):
        return 'rh'
    if user.has_group('hr.group_hr_user'):
        return 'manager'
    return 'employee'


def scopes_for_role(role):
    if role == 'rh':
        return BASE_SCOPES + MANAGER_EXTRA_SCOPES + RH_EXTRA_SCOPES
    if role == 'manager':
        return BASE_SCOPES + MANAGER_EXTRA_SCOPES
    return list(BASE_SCOPES)
