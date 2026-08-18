# -*- coding: utf-8 -*-
{
    'name': "Assistant RH IA - API Mobile (OAuth2/JWT)",
    'version': '17.0.1.2.0',
    'category': 'Human Resources',
    'summary': "Couche API REST (OAuth2/JWT) exposant les données RH à l'application mobile React.",
    'description': """
        Module technique dédié à l'exposition d'API REST pour l'application
        mobile Smart HR AI (React). Ne contient aucune logique métier RH :
        il fait uniquement le pont entre les modules Odoo (hr, hr_holidays,
        hr_attendance, hr_skills, hr_appraisal_ai, ...) et l'application mobile.

        Contenu de cette première itération :

        - Authentification OAuth2 / JWT (access token + refresh token)
        - Gestion des scopes selon le rôle (employé / manager / RH)
        - Premier endpoint métier protégé : consultation d'une fiche employé
        - Tableau de bord global (statistiques temps réel multi-modules)
        - Résumé hebdomadaire RH généré par IA (Gemini), manuel ou via cron hebdomadaire, avec filtre par département, affichage sur le dashboard et endpoint mobile de consultation
    """,
    'author': 'Votre Nom / Équipe',
    'website': 'https://www.example.com',
    'depends': [
        'base',
        'hr',
        'hr_recruitment_ai_assistant',
        'hr_holidays',
        'hr_leaves_ai',
        'hr_attendance',
        'hr_attendance_ai',
        'hr_skills',
        'hr_skills_ai',
        'hr_appraisal_ai',
    ],
    'external_dependencies': {
        'python': ['PyJWT'],  # PyJWT — pip install PyJWT
    },
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_weekly_summary.xml',
        'views/smart_hr_ai_dashboard_views.xml',
        'views/hr_weekly_summary_views.xml',
        'views/hr_employee_credentials_views.xml',
        'views/smart_hr_ai_menus.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
}
