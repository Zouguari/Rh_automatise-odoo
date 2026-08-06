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
        'project',
        'hr_contract',
        'hr_skills_ai',
        'hr_appraisal_ai',
        'hr_leaves_ai',
        'hr_attendance_ai',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/mail_templates.xml',
        'data/ir_cron_data.xml',
        'views/hr_recruitment_ai_views.xml',
        'views/hr_recruitment_ai_settings_views.xml',
        'views/hr_applicant_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_recruitment_stage_views.xml',
        'views/hr_recruitment_stage_repair_action.xml',
        'wizards/hr_applicant_merge_wizard_views.xml',
        'wizards/hr_applicant_bulk_import_wizard_views.xml',
        'views/hr_job_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'license': 'LGPL-3',
}