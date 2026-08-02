# -*- coding: utf-8 -*-
from .utils.jwt_helper import get_jwt_secret


def post_init_hook(env):
    """Pré-génère la clé secrète JWT dès l'installation du module, plutôt
    que de la laisser être créée au hasard lors du tout premier appel API
    (comportement moins prévisible, notamment avec plusieurs workers)."""
    get_jwt_secret(env)
