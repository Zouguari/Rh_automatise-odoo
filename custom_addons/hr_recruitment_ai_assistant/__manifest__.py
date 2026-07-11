# -*- coding: utf-8 -*-
{
    'name': 'Assistant RH & Recrutement IA',
    'version': '1.0.0',
    'category': 'Human Resources',
    'summary': 'Assistant intelligent pour le recrutement et la gestion des ressources humaines basé sur l\'IA.',
    'description': """
        Ce module intègre des fonctionnalités d'intelligence artificielle pour assister
        les recruteurs et les gestionnaires RH :
        - Analyse automatique de CV.
        - Génération de descriptions de postes.
        - Aide à l'évaluation des candidats.
    """,
    'author': 'Votre Nom / Équipe',
    'website': 'https://www.example.com',
    'depends': [
        'hr',
        'hr_recruitment',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/mail_templates.xml',
        'views/hr_recruitment_ai_views.xml',
        'views/hr_applicant_views.xml',
        'views/hr_job_views.xml',
        'views/hr_recruitment_stage_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
