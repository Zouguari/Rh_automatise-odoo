# -*- coding: utf-8 -*-
{
    'name': "Assistant RH IA - API Mobile (OAuth2/JWT)",
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Couche API REST (OAuth2/JWT) exposant les données RH à l'application mobile React.",
    'description': """
        Module technique dédié à l'exposition d'API REST pour l'application
        mobile Smart HR AI (React). Ne contient aucune logique métier RH :
        il fait uniquement le pont entre les modules Odoo (hr, hr_holidays,
        hr_attendance, hr_skills, hr_appraisal, ...) et l'application mobile.

        Contenu de cette première itération :
        - Authentification OAuth2 / JWT (access token + refresh token)
        - Gestion des scopes selon le rôle (employé / manager / RH)
        - Premier endpoint métier protégé : consultation d'une fiche employé
    """,
    'author': 'Votre Nom / Équipe',
    'website': 'https://www.example.com',
    'depends': [
        'base',
        'hr',
        'hr_holidays',
        'hr_leaves_ai',
    ],
    'external_dependencies': {
        'python': ['jwt'],  # PyJWT — pip install PyJWT
    },
    'data': [
        'security/ir.model.access.csv',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
}
