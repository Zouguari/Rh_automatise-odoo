# -*- coding: utf-8 -*-
"""Tests unitaires sur le pipeline Candidature -> Employé de
hr_recruitment_ai_assistant.

Ces tests couvrent l'ORCHESTRATION métier (assignation recruteur,
détection de doublons, automatisation par étape, création employé/contrat),
PAS la qualité des réponses IA elles-mêmes. Tous les appels Gemini sont
mockés au niveau de HrApplicant._call_gemini_json — le point d'entrée
unique partagé par l'extraction, le scoring, le matching et la génération
de questions d'entretien (voir hr_applicant.py). Ça permet de tester la
logique métier réelle sans dépendre du réseau ni de la qualité du modèle,
et sans faire exploser le temps d'exécution des tests.
"""
import unittest
from unittest.mock import patch

try:
    from odoo.tests.common import TransactionCase, tagged
    from odoo.exceptions import ValidationError, UserError
    HAS_ODOO = True
except (ImportError, AttributeError):
    HAS_ODOO = False
    TransactionCase = unittest.TestCase
    ValidationError = Exception
    UserError = Exception
    def tagged(*args, **kwargs):
        return lambda cls: cls


@tagged('post_install', '-at_install')
class TestRecruitmentPipeline(TransactionCase):
    """Tests d'intégration légers sur le pipeline de recrutement IA."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not HAS_ODOO:
            return

        cls.department = cls.env['hr.department'].create({
            'name': 'Département Test IA',
        })
        cls.recruiter = cls.env['res.users'].create({
            'name': 'Recruteur Test',
            'login': 'recruteur.test.pipeline@example.com',
            'email': 'recruteur.test.pipeline@example.com',
        })
        cls.job = cls.env['hr.job'].create({
            'name': 'Développeur Odoo Test',
            'department_id': cls.department.id,
            'user_id': cls.recruiter.id,
            'required_skills': 'Python\nOdoo\nPostgreSQL',
        })

        # Étapes dédiées à ces tests, indépendantes de ce que le hook
        # post_init a pu configurer par ailleurs (même approche que
        # test_hr_recruitment_stage.py : ne pas dépendre des données
        # d'install pour rester isolé et reproductible).
        cls.stage_new = cls.env['hr.recruitment.stage'].create({
            'name': 'Nouveau (Test Pipeline)',
        })
        cls.stage_interview_rh = cls.env['hr.recruitment.stage'].create({
            'name': 'Entretien RH (Test Pipeline)',
            'is_interview_stage': True,
            'interview_type': 'rh',
        })
        cls.stage_contract_signed = cls.env['hr.recruitment.stage'].create({
            'name': 'Contrat Signé (Test Pipeline)',
            'is_contract_signed_stage': True,
        })
        cls.stage_refused = cls.env['hr.recruitment.stage'].create({
            'name': 'Refusé (Test Pipeline)',
            'is_refusal_stage': True,
        })

    def _create_applicant(self, **overrides):
        vals = {
            # 'name' (Sujet / Candidature) est requis nativement par
            # hr.applicant (hr_recruitment) — il n'est jamais déduit
            # automatiquement de partner_name. Absent d'ici jusqu'ici, ce
            # qui provoquait une NotNullViolation PostgreSQL dès que ce
            # fichier de test s'exécutait réellement pour la première fois.
            'name': 'Candidature Test',
            'partner_name': 'Candidat Test',
            'email_from': 'candidat.test.pipeline@example.com',
            'job_id': self.job.id,
            'stage_id': self.stage_new.id,
        }
        vals.update(overrides)
        return self.env['hr.applicant'].create(vals)

    # ------------------------------------------------------------------
    # 1. Assignation automatique du recruteur
    # ------------------------------------------------------------------

    def test_create_assigns_recruiter_from_job(self):
        """A la création, si aucun recruteur n'est précisé, celui du poste
        (hr.job.user_id) doit être repris automatiquement."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        applicant = self._create_applicant()
        self.assertEqual(
            applicant.user_id, self.recruiter,
            "Le recruteur du poste doit être assigné automatiquement à la candidature."
        )

    def test_create_does_not_override_explicit_recruiter(self):
        """Si un recruteur est explicitement fourni à la création, il ne
        doit PAS être écrasé par celui du poste."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        other_recruiter = self.env['res.users'].create({
            'name': 'Autre Recruteur',
            'login': 'autre.recruteur.pipeline@example.com',
            'email': 'autre.recruteur.pipeline@example.com',
        })
        applicant = self._create_applicant(user_id=other_recruiter.id)
        self.assertEqual(applicant.user_id, other_recruiter)

    # ------------------------------------------------------------------
    # 2. Exclusivité des rôles d'étape
    # ------------------------------------------------------------------

    def test_stage_cannot_have_two_automatic_roles(self):
        """Une étape ne peut pas être marquée à la fois 'entretien' et
        'contrat signé' (rôles automatiques contradictoires)."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        with self.assertRaises(ValidationError):
            self.env['hr.recruitment.stage'].create({
                'name': 'Étape Invalide (Test)',
                'is_interview_stage': True,
                'is_contract_signed_stage': True,
            })

    # ------------------------------------------------------------------
    # 3. Détection de doublons
    # ------------------------------------------------------------------

    def test_duplicate_detection_by_email(self):
        """Deux candidatures avec le même email doivent toutes deux être
        marquées comme doublon potentiel. NOTE : duplicate_applicant_ids
        n'est peuplé QUE sur le candidat pour lequel _find_duplicate_applicants()
        vient de tourner (ici : 'second', créé après 'first') — le doublon
        retrouvé ('first') ne voit que son flag is_potential_duplicate mis
        à jour, pas sa propre liste. Voir action_detect_duplicates() :
        seul is_potential_duplicate est propagé aux deux côtés. C'est le
        comportement RÉEL actuel (pas forcément le comportement idéal —
        une liste symétrique serait plus pratique pour naviguer d'un
        candidat à l'autre depuis l'UI, à discuter séparément)."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        first = self._create_applicant(email_from='doublon.pipeline@example.com')
        second = self._create_applicant(
            partner_name='Candidat Test 2',
            email_from='doublon.pipeline@example.com',
        )

        self.assertTrue(first.is_potential_duplicate)
        self.assertTrue(second.is_potential_duplicate)
        self.assertIn(
            first, second.duplicate_applicant_ids,
            "'second' doit référencer 'first' (trouvé par _find_duplicate_applicants)."
        )
        self.assertFalse(
            first.duplicate_applicant_ids,
            "Comportement actuel : 'first' n'est pas mis à jour en retour "
            "(seul son flag is_potential_duplicate l'est)."
        )

    def test_no_duplicate_detected_for_distinct_applicants(self):
        """Deux candidatures sans point commun (email/téléphone/nom) ne
        doivent pas être marquées comme doublons."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        first = self._create_applicant(
            partner_name='Personne Unique A', email_from='unique.a.pipeline@example.com',
        )
        second = self._create_applicant(
            partner_name='Personne Unique B', email_from='unique.b.pipeline@example.com',
        )
        self.assertFalse(first.is_potential_duplicate)
        self.assertFalse(second.is_potential_duplicate)

    # ------------------------------------------------------------------
    # 4. Passage à l'étape "Entretien" -> génération IA + planification
    # ------------------------------------------------------------------

    def test_reaching_interview_stage_schedules_interview(self):
        """Déplacer un candidat vers une étape marquée is_interview_stage
        doit générer les questions IA (mockées) et planifier un entretien
        (événement calendrier + hr.applicant.interview)."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        applicant = self._create_applicant()
        # L'extraction CV n'est pas testée ici : on simule juste son résultat,
        # requis par action_generate_interview_questions (garde-fou du code).
        applicant.ai_summary = "Résumé de test pour le candidat."

        with patch(
            'odoo.addons.hr_recruitment_ai_assistant.models.hr_applicant.HrApplicant._call_gemini_json',
            return_value={'questions': ['Question test 1 ?', 'Question test 2 ?']},
        ) as mocked_gemini:
            applicant.write({'stage_id': self.stage_interview_rh.id})

        mocked_gemini.assert_called_once()
        self.assertTrue(applicant.ai_interview_questions)
        self.assertIn('Question test 1', applicant.ai_interview_questions)
        self.assertTrue(applicant.interview_event_id)
        self.assertEqual(applicant.last_scheduled_interview_stage_id, self.stage_interview_rh)

        interview_records = self.env['hr.applicant.interview'].search([
            ('applicant_id', '=', applicant.id),
        ])
        self.assertEqual(len(interview_records), 1)
        self.assertEqual(interview_records.stage_id, self.stage_interview_rh)

    # ------------------------------------------------------------------
    # 5. Passage à l'étape "Contrat signé" -> Applicant -> Employee
    # ------------------------------------------------------------------

    def test_reaching_contract_signed_stage_creates_employee_and_activates_contract(self):
        """C'est LE test du pipeline Candidature -> Employé : déplacer un
        candidat vers l'étape 'contrat signé' doit, en cascade :
        - créer l'employé (emp_id renseigné)
        - générer un contrat en brouillon puis le passer à l'état 'open'
        - tracer le succès de l'email de félicitations dans le chatter."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        applicant = self._create_applicant(
            email_from='futur.employe.pipeline@example.com',
            partner_name='Futur Employé Pipeline',
        )

        applicant.write({'stage_id': self.stage_contract_signed.id})

        self.assertTrue(applicant.emp_id, "L'employé doit être créé automatiquement.")
        self.assertTrue(applicant.generated_contract_id, "Le contrat doit être généré automatiquement.")
        self.assertEqual(
            applicant.generated_contract_id.state, 'open',
            "Le contrat doit être automatiquement validé (état 'En cours')."
        )
        self.assertEqual(applicant.emp_id.department_id, self.department)

        # NOTE : mail.mail est créé avec auto_delete=True dans
        # _send_email_safely (voir hr_applicant.py) — volontaire, pour ne
        # pas polluer la table. Si l'envoi réussit réellement (serveur SMTP
        # configuré dans l'environnement de test), le record disparaît
        # immédiatement après envoi. Le succès est tracé de façon durable
        # dans le chatter via message_post(log_success) — c'est là qu'il
        # faut vérifier, pas dans mail.mail.
        acceptance_logged = any(
            'félicitations' in (msg.body or '').lower()
            for msg in applicant.message_ids
        )
        self.assertTrue(
            acceptance_logged,
            "Le succès de l'envoi de l'email de félicitations doit être tracé "
            "dans le chatter (mail.mail est supprimé après envoi réussi : "
            "voir _send_email_safely, auto_delete=True — volontaire)."
        )

        onboarding_tasks = self.env['project.task'].search([
            ('applicant_origin_id', '=', applicant.id),
        ])
        self.assertEqual(
            len(onboarding_tasks), 6,
            "Les 6 tâches d'onboarding standard doivent être créées."
        )

    def test_create_employee_from_applicant_blocks_when_active_employee_exists(self):
        """Si un employé ACTIF existe déjà avec le même email, la conversion
        doit être BLOQUÉE avec un message clair — pas de réutilisation
        silencieuse (qui réapplique l'onboarding IA sur une personne déjà
        en poste, voir docstring de create_employee_from_applicant) ni de
        création en double."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        existing_employee = self.env['hr.employee'].create({
            'name': 'Personne Déjà Connue',
            'work_email': 'deja.connue.pipeline@example.com',
        })
        applicant = self._create_applicant(
            partner_name='Personne Déjà Connue',
            email_from='deja.connue.pipeline@example.com',
        )

        employee_count_before = self.env['hr.employee'].search_count([])

        with self.assertRaises(UserError):
            applicant.create_employee_from_applicant()

        self.assertFalse(
            applicant.emp_id,
            "La candidature ne doit PAS être rattachée à l'employé existant automatiquement."
        )
        self.assertEqual(
            self.env['hr.employee'].search_count([]), employee_count_before,
            "Aucun employé (ni doublon, ni rattachement) ne doit être créé/modifié."
        )
        self.assertEqual(
            self.env['hr.appraisal'].search_count([('employee_id', '=', existing_employee.id)]), 0,
            "Aucune évaluation ne doit être créée sur l'employé existant suite à ce blocage."
        )

    def test_reaching_contract_signed_stage_is_blocked_when_active_employee_exists(self):
        """Reproduit le scénario réel : une personne déjà employée (poste A)
        postule pour un second poste (poste B) et le recruteur fait avancer
        cette 2e candidature jusqu'à 'Contrat signé'. Le changement d'étape
        lui-même doit être bloqué (UserError remontée depuis
        _handle_contract_signed_stage, voir le `raise` explicite sur
        UserError dans son except) plutôt que d'avancer silencieusement en
        laissant une note dans le chatter."""
        if not HAS_ODOO:
            self.skipTest("Environnement Odoo non actif.")

        existing_employee = self.env['hr.employee'].create({
            'name': 'Déjà Employé Ailleurs',
            'work_email': 'deja.employe.pipeline@example.com',
        })
        second_applicant = self._create_applicant(
            partner_name='Déjà Employé Ailleurs',
            email_from='deja.employe.pipeline@example.com',
            name='Candidature Poste B (Test)',
        )

        with self.assertRaises(Exception):
            second_applicant.write({'stage_id': self.stage_contract_signed.id})

        second_applicant.invalidate_recordset()
        self.assertNotEqual(
            second_applicant.stage_id, self.stage_contract_signed,
            "L'étape ne doit PAS avoir avancé : le write() entier doit être annulé "
            "(rollback), pas seulement la création d'employé."
        )
        self.assertFalse(second_applicant.emp_id)
        self.assertEqual(
            self.env['hr.appraisal'].search_count([('employee_id', '=', existing_employee.id)]), 0,
            "L'évaluation IA de l'employé existant ne doit pas être touchée."
        )


if __name__ == '__main__':
    unittest.main()