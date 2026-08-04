# -*- coding: utf-8 -*-
{
    'name': "Assistant RH IA - Gestion des compétences",
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Analyse des compétences, détection de lacunes, recommandations de formation.",
    'description': """
Module metier (aucune route HTTP ici, voir hr_ai_api) qui ajoute la gestion des competences requises par poste (hr.job.skill), un petit catalogue de formations (hr.training.course), et deux methodes sur hr.employee (get_skill_gap_analysis, get_career_path) qui comparent les competences actuelles de l'employe a celles requises par un poste et recommandent des formations en consequence. L'analyse n'est pas stockee en base : elle depend du poste choisi et est recalculee a la demande.
    """,
    'author': 'Votre Nom / Équipe',
    'depends': ['hr_skills'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_job_skill_views.xml',
        'views/hr_training_course_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
