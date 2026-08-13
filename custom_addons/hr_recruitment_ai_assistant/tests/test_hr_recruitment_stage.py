# -*- coding: utf-8 -*-
"""Tests unitaires sur la configuration des étapes de recrutement
(hr.recruitment.stage) de hr_recruitment_ai_assistant.

NOTE DE MIGRATION : ce fichier testait auparavant une fonction
`_mark_default_interview_stages(env)` définie dans hooks.py. Cette
fonction n'existe plus : la configuration du pipeline standard a été
généralisée de 2 étapes d'entretien à un pipeline complet de 7 étapes
(Nouveau, Qualification initiale, Entretien RH, Entretien Technique,
Proposition de contrat, Contrat signé, Refusé), pilotée par rôle
(is_interview_stage / is_refusal_stage / is_contract_signed_stage) plutôt
que par nom, et implémentée comme méthode du modèle
hr.recruitment.stage._setup_default_pipeline_stages() (voir
models/hr_recruitment_stage.py). hooks.post_init_hook() se contente
désormais d'appeler cette méthode.

L'import de l'ancienne fonction `_mark_default_interview_stages` faisait
planter le CHARGEMENT DU MODULE entier (AttributeError levée à l'import
de tests/__init__.py, avant même l'exécution d'un test), pas seulement un
test — d'où l'échec systématique de `-u hr_recruitment_ai_assistant
--test-enable`. Ce fichier a été réécrit pour cibler l'API réellement
existante aujourd'hui.
"""
import unittest
from unittest.mock import patch

try:
    from odoo.tests.common import TransactionCase, tagged
    HAS_ODOO = True
except (ImportError, AttributeError):
    HAS_ODOO = False
    TransactionCase = unittest.TestCase

    def tagged(*args, **kwargs):
        return lambda cls: cls

# Import du hook réel, de façon sécurisée (compatible hors-Odoo pour
# l'analyse statique, et dans Odoo pour l'exécution des tests). Contrairement
# à l'ancienne version, on n'importe plus de fonction inexistante : juste le
# hook d'installation tel qu'il existe réellement dans hooks.py.
try:
    from odoo.addons.hr_recruitment_ai_assistant.hooks import post_init_hook
except ImportError:
    post_init_hook = None


@tagged('post_install', '-at_install')
class TestHrRecruitmentStage(TransactionCase):
    """Tests unitaires Odoo pour la personnalisation des étapes de
    recrutement RH & IA (champs de rôle + configuration automatique du
    pipeline standard)."""

    def setUp(self):
        super(TestHrRecruitmentStage, self).setUp()
        if HAS_ODOO and hasattr(self, 'env'):
            self.stage_model = self.env['hr.recruitment.stage']

    def _clear_conflicting_stage(self, target_name, interview_type):
        """Écarte toute étape déjà présente en base qui porte déjà le NOM
        cible ou le RÔLE recherché, avant de mettre en place un scénario de
        test isolé.

        Nécessaire car ces tests (tag 'post_install') s'exécutent sur la
        base APRÈS l'installation réelle du module : post_init_hook a déjà
        appelé _setup_default_pipeline_stages() et créé les étapes
        canoniques ('Entretien RH', 'Entretien Technique', déjà marquées
        avec leur rôle). Sans cet écartement, un scénario qui suppose
        "aucune étape ne porte encore ce nom/ce rôle" entre en collision
        avec ces données réelles déjà présentes, et le test observe le
        comportement de CETTE étape préexistante plutôt que celui du
        scénario qu'il met en place.

        On ne supprime jamais l'étape (une candidature pourrait y être
        rattachée) : on la renomme et lui retire son rôle, ce qui suffit à
        la sortir du champ de recherche de _setup_default_pipeline_stages().
        Comme chaque méthode de test s'exécute dans sa propre savepoint
        (rollback automatique par TransactionCase), cet écartement ne
        laisse aucune trace en dehors du test courant."""
        Stage = self.stage_model
        conflicting = Stage.search([
            '|',
            ('name', '=', target_name),
            '&', ('is_interview_stage', '=', True), ('interview_type', '=', interview_type),
        ])
        for i, stage in enumerate(conflicting):
            stage.write({
                'name': f"{stage.name} (écartée pour {self._testMethodName} #{i})",
                'is_interview_stage': False,
                'interview_type': False,
            })

    # ------------------------------------------------------------------
    # 1. Champs de rôle sur hr.recruitment.stage
    # ------------------------------------------------------------------

    def test_stage_interview_type_fields(self):
        """Vérifie la création et la mise à jour des champs interview_type
        et is_interview_stage."""
        if not HAS_ODOO or not hasattr(self, 'env'):
            self.skipTest("Environnement Odoo non actif - test d'intégration ignoré en standalone.")

        stage_rh = self.stage_model.create({
            'name': 'Entretien RH Test',
            'is_interview_stage': True,
            'interview_type': 'rh',
        })
        self.assertTrue(stage_rh.is_interview_stage)
        self.assertEqual(stage_rh.interview_type, 'rh')

        stage_tech = self.stage_model.create({
            'name': 'Entretien Technique Test',
            'is_interview_stage': True,
            'interview_type': 'technique',
        })
        self.assertTrue(stage_tech.is_interview_stage)
        self.assertEqual(stage_tech.interview_type, 'technique')

    # ------------------------------------------------------------------
    # 2. _setup_default_pipeline_stages() : reprise d'un ancien nom Odoo
    # ------------------------------------------------------------------

    def test_setup_pipeline_renames_legacy_named_stage_without_duplicating(self):
        """Si aucune étape ne porte déjà le rôle 'entretien RH'/'entretien
        technique', mais qu'une étape porte encore un ancien nom par défaut
        Odoo (ex: 'First Interview'), _setup_default_pipeline_stages() doit
        RENOMMER cette étape existante et lui appliquer le rôle, plutôt que
        d'en créer une nouvelle à côté (préserve les candidats déjà dessus)."""
        if not HAS_ODOO or not hasattr(self, 'env'):
            self.skipTest("Environnement Odoo non actif - test d'intégration ignoré en standalone.")

        Stage = self.stage_model

        # Écarte toute étape déjà présente en base portant soit le NOM
        # cible ('Entretien RH'/'Entretien Technique' — typiquement déjà
        # créées par post_init_hook lors de l'installation réelle du
        # module), soit déjà le rôle, afin d'isoler proprement la branche
        # "reprise d'un ancien nom Odoo" testée ici.
        self._clear_conflicting_stage('Entretien RH', 'rh')
        self._clear_conflicting_stage('Entretien Technique', 'technique')

        legacy_rh = Stage.create({'name': 'First Interview'})
        legacy_tech = Stage.create({'name': 'Second Interview'})

        Stage._setup_default_pipeline_stages()

        legacy_rh.invalidate_recordset()
        legacy_tech.invalidate_recordset()

        self.assertEqual(legacy_rh.name, 'Entretien RH')
        self.assertTrue(legacy_rh.is_interview_stage)
        self.assertEqual(legacy_rh.interview_type, 'rh')

        self.assertEqual(legacy_tech.name, 'Entretien Technique')
        self.assertTrue(legacy_tech.is_interview_stage)
        self.assertEqual(legacy_tech.interview_type, 'technique')

        # Aucun doublon ne doit avoir été créé pour l'un ou l'autre rôle.
        self.assertEqual(
            Stage.search_count([('is_interview_stage', '=', True), ('interview_type', '=', 'rh')]),
            1,
        )
        self.assertEqual(
            Stage.search_count([('is_interview_stage', '=', True), ('interview_type', '=', 'technique')]),
            1,
        )

    # ------------------------------------------------------------------
    # 3. _setup_default_pipeline_stages() : priorité au rôle déjà actif
    # ------------------------------------------------------------------

    def test_setup_pipeline_does_not_touch_stage_already_carrying_role(self):
        """Une étape qui porte DÉJÀ le rôle 'entretien RH', même sous un
        nom personnalisé par le recruteur, ne doit jamais être renommée ni
        dupliquée par _setup_default_pipeline_stages() — le rôle prime
        toujours sur le nom cible."""
        if not HAS_ODOO or not hasattr(self, 'env'):
            self.skipTest("Environnement Odoo non actif - test d'intégration ignoré en standalone.")

        Stage = self.stage_model

        # Écarte toute étape déjà présente en base (ex: 'Entretien RH'
        # créée par post_init_hook à l'installation réelle) avant de mettre
        # en place NOTRE unique porteuse du rôle pour ce scénario — sinon
        # le compte de porteurs du rôle serait faussé dès le départ par des
        # données réelles indépendantes du scénario testé.
        self._clear_conflicting_stage('Entretien RH', 'rh')

        custom_stage = Stage.create({
            'name': 'Entretien RH (Personnalisé)',
            'is_interview_stage': True,
            'interview_type': 'rh',
        })

        Stage._setup_default_pipeline_stages()
        custom_stage.invalidate_recordset()

        self.assertEqual(
            custom_stage.name, 'Entretien RH (Personnalisé)',
            "Le nom personnalisé d'une étape portant déjà le rôle actif ne doit jamais être écrasé.",
        )
        self.assertEqual(
            Stage.search_count([('is_interview_stage', '=', True), ('interview_type', '=', 'rh')]),
            1,
            "Aucune deuxième étape 'Entretien RH' ne doit être créée en doublon.",
        )

    # ------------------------------------------------------------------
    # 4. hooks.post_init_hook() délègue bien à la méthode du modèle
    # ------------------------------------------------------------------

    def test_post_init_hook_delegates_to_setup_default_pipeline_stages(self):
        """post_init_hook(env) doit se contenter d'appeler
        hr.recruitment.stage._setup_default_pipeline_stages() — c'est la
        seule responsabilité du hook aujourd'hui, toute la logique de
        configuration du pipeline vit dans la méthode du modèle."""
        if not HAS_ODOO or not hasattr(self, 'env'):
            self.skipTest("Environnement Odoo non actif - test d'intégration ignoré en standalone.")
        if post_init_hook is None:
            self.skipTest("hooks.post_init_hook n'a pas pu être importé dans cet environnement.")

        with patch(
            'odoo.addons.hr_recruitment_ai_assistant.models.hr_recruitment_stage'
            '.HrRecruitmentStage._setup_default_pipeline_stages'
        ) as mocked_setup:
            post_init_hook(self.env)

        mocked_setup.assert_called_once()


if __name__ == '__main__':
    unittest.main()