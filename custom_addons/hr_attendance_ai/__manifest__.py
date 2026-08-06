# -*- coding: utf-8 -*-
{
    'name': "Assistant RH IA - Gestion des présences",
    'version': '17.0.1.0.0',
    'category': 'Human Resources',
    'summary': "Détection automatique des retards, anomalies de présence et alertes.",
    'description': """
        Module métier (aucune route HTTP ici, voir hr_ai_api) qui enrichit
        hr.attendance avec :
        - La détection de retard par rapport au calendrier de travail de
          l'employé (is_late, late_minutes)
        - La détection d'anomalies (pointage de sortie manquant, retards
          répétés) via hr.attendance.anomaly, alimenté par un cron quotidien

        Logique volontairement simple (heuristique à base de règles) pour
        cette première itération, comme pour hr_leaves_ai.
    """,
    'author': 'Votre Nom / Équipe',
    'depends': ['hr_attendance'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/hr_attendance_ai_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
