# hr_ai_api — Installation et test

## 1. Installation

1. Copier le dossier `hr_ai_api/` dans votre répertoire d'addons personnalisés
   (à côté de `hr_recruitment_ai_assistant/`).
2. Installer la dépendance Python dans l'image Docker (voir Dockerfile fourni,
   ligne `PyJWT` ajoutée à la liste `pip install`), puis rebuild :
   ```bash
   docker-compose build
   docker-compose up -d
   ```
3. Dans Odoo (`http://localhost:8070`) : mode développeur activé →
   **Apps** → **Mettre à jour la liste des Apps** → chercher `hr_ai_api` → **Installer**.

## 2. Important : ce sont de vraies routes REST (type='http'), pas du JSON-RPC

Toutes les routes de ce module utilisent `type='http'` côté Odoo : le corps
de requête est du JSON brut, et la réponse est du JSON brut (pas
d'enveloppe `{"jsonrpc": "2.0", ...}`). C'est un choix volontaire pour que
l'app mobile consomme une API REST standard.

## 3. Tester avec curl (Linux/Mac, ou curl.exe sous Windows)

```bash
# 1. Obtenir un token
curl -X POST http://localhost:8070/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"login": "admin", "password": "admin", "device": "test-curl"}'

# 2. Appeler une route protégée
curl http://localhost:8070/api/v1/auth/me \
  -H "Authorization: Bearer <access_token_recu>"

# 3. Consulter une fiche employé
curl http://localhost:8070/api/v1/employees/1 \
  -H "Authorization: Bearer <access_token_recu>"

# 4. Rafraîchir
curl -X POST http://localhost:8070/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<refresh_token_recu>"}'

# 5. Révoquer (déconnexion)
curl -X POST http://localhost:8070/api/v1/auth/revoke \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<refresh_token_recu>"}'
```

## 4. Tester avec PowerShell (Windows)

Sous PowerShell, `curl` est un alias d'`Invoke-WebRequest` et n'accepte pas
la syntaxe `-X` / `-H` / `-d` : utilisez `Invoke-RestMethod` directement,
ou `curl.exe` (avec l'extension explicite) pour la vraie commande curl.

```powershell
# 1. Obtenir un token
$response = Invoke-RestMethod `
  -Uri "http://localhost:8070/api/v1/auth/token" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"login":"admin","password":"admin","device":"test-curl"}'

$response
$accessToken = $response.access_token
$refreshToken = $response.refresh_token

# 2. Appeler une route protégée
Invoke-RestMethod `
  -Uri "http://localhost:8070/api/v1/auth/me" `
  -Method GET `
  -Headers @{ Authorization = "Bearer $accessToken" }

# 3. Consulter une fiche employé
Invoke-RestMethod `
  -Uri "http://localhost:8070/api/v1/employees/1" `
  -Method GET `
  -Headers @{ Authorization = "Bearer $accessToken" }

# 4. Rafraîchir
Invoke-RestMethod `
  -Uri "http://localhost:8070/api/v1/auth/refresh" `
  -Method POST `
  -ContentType "application/json" `
  -Body (@{ refresh_token = $refreshToken } | ConvertTo-Json)
```

Si `Invoke-RestMethod` reçoit une erreur HTTP (400/401/403), PowerShell lève
une exception au lieu d'afficher le JSON d'erreur. Pour le voir :
```powershell
try {
  Invoke-RestMethod -Uri "..." -Method POST -ContentType "application/json" -Body '...'
} catch {
  $_.ErrorDetails.Message
}
```

## 5. Points à vérifier / adapter selon votre version exacte d'Odoo 17

- `controllers/auth.py`, méthode `auth_token` : la signature exacte de
  `res.users.authenticate(db, credential, user_agent_env)` peut varier
  selon le correctif mineur d'Odoo 17 installé. Si l'authentification
  échoue systématiquement en environnement réel, vérifier la signature
  dans `odoo/addons/base/models/res_users.py` de votre installation, et
  regarder `docker-compose logs -f web` pour la trace d'erreur exacte.
- Les scopes définis dans `utils/roles.py` sont un point de départ
  (`profile:read`, `leaves:read`, ...) : ils seront complétés au fur et à
  mesure de l'implémentation des modules Congés, Présences, etc.

## 6. Prochaine étape

Une fois ces routes validées, enchaîner sur le module **Gestion des congés**
(section 5.2 du document d'architecture) : nouveaux champs IA sur
`hr.leave`, puis endpoints `/api/v1/leaves/...` protégés par les scopes
`leaves:read` / `leaves:write` / `leaves:approve` déjà en place.
