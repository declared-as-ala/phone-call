# Installation client — Windows 10 (TeamViewer)

Guide pour **toi** (développeur) qui installes le dashboard sur le PC du client via **TeamViewer**. Le client n’installe rien seul : il ouvre TeamViewer et te donne la main.

---

## Ce que le client doit faire (5 minutes)

1. Installer **TeamViewer** et te donner ID + mot de passe (ou accepter ton invitation).
2. Rester disponible pour saisir **mots de passe SIP / LuvVoice** si tu ne les as pas déjà.
3. Après installation : ouvrir **Chrome** ou **Edge** sur `http://localhost:5173` et se connecter avec le compte que tu crées.

---

## Ce que tu installes sur sa machine (ordre)

### 1. Logiciels (téléchargements officiels)

| Logiciel | Lien / note |
|----------|-------------|
| **Python 3.10 ou 3.11** | https://www.python.org/downloads/ — cocher **“Add python.exe to PATH”** à l’installation |
| **Node.js 18 LTS** | https://nodejs.org/ |
| **Git for Windows** | https://git-scm.com/download/win — pour **Git Bash** (scripts `.sh`) |
| **ffmpeg** | https://www.gyan.dev/ffmpeg/builds/ — extraire, ajouter le dossier `bin` au **PATH** système |
| **Docker Desktop** | https://www.docker.com/products/docker-desktop/ — **uniquement** pour de **vrais appels** (SIP UP) |

Redémarrer le PC après Python + PATH si les commandes ne sont pas reconnues.

### 2. Recevoir le code (sans GitHub)

Le développeur t’envoie **`ivr-dashboard-YYYYMMDD.zip`** par :

- **Email** si le fichier fait **&lt; 20 Mo** (Gmail limite ~25 Mo) ;
- sinon **WeTransfer**, **Google Drive**, **Dropbox**, ou **clé USB** en TeamViewer.

À l’extraction : dossier type `C:\ivr-project`.

**Dans le zip il ne doit pas y avoir** : `backend\.env` (secrets), `node_modules`, `.venv` — tu les recrées sur le PC avec les commandes d’installation ci-dessous.

**Créer le zip (développeur, Mac)** : `bash scripts/package-for-client.sh`  
**Créer le zip (développeur, Windows)** : clic droit PowerShell → `scripts\windows\package-for-client.ps1`

**Ne pas** écraser un `backend\.env` existant du client sans sauvegarde.

---

## Installation — une seule commande

Après extraction du zip dans `C:\ivr-project` :

**Double-clic** ou dans **cmd** :

```bat
C:\ivr-project\scripts\windows\install-all.cmd
```

Ça installe tout : venv Python, `pip install`, base de données (`alembic`), `npm install` frontend, et crée `backend\.env` si absent.

Prérequis déjà installés : **Python 3.10+** (Add to PATH), **Node.js 18+**.

Puis éditer `backend\.env` :

| Usage | `TELEPHONY_PROVIDER` |
|-------|----------------------|
| **Démo** (pas de vrai téléphone) | `mock` |
| **Vrais appels** | `sip_up` + remplir `SIPUP_*`, `ASTERISK_*`, `LUVVOICE_API_TOKEN` |

Créer le compte admin (une fois) :

```bat
cd C:\ivr-project\backend
.venv\Scripts\activate.bat
python scripts\create_admin.py --email client@example.com --password "MotDePasseFort1!" --full-name "Admin Client"
```

Mot de passe : **12+ caractères**, majuscule, minuscule, chiffre, symbole.

**Git Bash** (alternative) : `bash scripts/install-all.sh` depuis la racine du projet.

Pour le dev local, **ne pas** mettre `VITE_API_BASE_URL=http://localhost:8000` dans `.env.local` (le proxy Vite gère `/api`).

---

## Démarrer l’application (chaque jour)

### Option A — Scripts Windows (double-clic)

Sur le Bureau du client, raccourcis vers :

- `C:\ivr-project\scripts\windows\start-backend.cmd`
- `C:\ivr-project\scripts\windows\start-frontend.cmd`

Puis navigateur : **http://localhost:5173** (ou **5174** si le terminal l’indique).

### Option B — Git Bash (3 terminaux)

```bash
# Terminal 1 — backend
cd /c/ivr-project && bash scripts/run_backend.sh

# Terminal 2 — frontend
cd /c/ivr-project && bash scripts/run_frontend.sh

# Terminal 3 — seulement si TELEPHONY_PROVIDER=sip_up
cd /c/ivr-project && bash scripts/run_sipup_bridge.sh
```

### Option C — PowerShell manuel

```powershell
cd C:\ivr-project\backend
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "."
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Autre fenêtre :

```powershell
cd C:\ivr-project\frontend
npm run dev
```

---

## Vrais appels sur Windows 10 (SIP UP)

1. Installer **Docker Desktop**, le lancer (icône verte).
2. Dans `infra\sipup`, copier les fichiers `.example` vers les vrais configs (voir `infra\sipup\README.md`).
3. Git Bash :

   ```bash
   cd /c/ivr-project/infra/sipup
   docker compose up -d
   ```

4. `backend\.env` : `TELEPHONY_PROVIDER=sip_up`, mots de passe ARI alignés avec `infra\sipup\config\ari.conf`.
5. Lancer **backend + frontend + bridge** (`run_sipup_bridge.sh` ou équivalent).
6. Pare-feu Windows : autoriser **Python** et **Node** sur réseau privé si le navigateur ne charge pas l’API.

---

## Vérifications rapides

| Test | Commande / action |
|------|-------------------|
| Python | `python --version` |
| Node | `node --version` |
| ffmpeg | `ffmpeg -version` |
| API | Navigateur ou `curl http://127.0.0.1:8000/api/system/runtime` → 401 = OK |
| UI | http://localhost:5173 → écran de connexion |

---

## Problèmes fréquents Windows 10

| Symptôme | Solution |
|----------|----------|
| `python` introuvable | Réinstaller Python avec **Add to PATH**, ou redémarrer |
| `ExecutionPolicy` PowerShell | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| **Failed to fetch** au login | Backend pas lancé ; utiliser l’URL Vite (`5173`), pas seulement `:8000` sans CORS |
| Port 5173 occupé | Utiliser l’URL affichée par Vite (`5174`, etc.) |
| LuvVoice preview silencieux | Vérifier `LUVVOICE_API_TOKEN` + `ffmpeg` dans PATH |
| Docker ne démarre pas | WSL2 / virtualisation activée dans le BIOS |

---

## Phrase pour le client

> « Sur Windows 10, tu m’ouvres TeamViewer. J’installe Python, Node et l’application. Ensuite tu double-cliques sur les raccourcis “IVR Backend” et “IVR Frontend”, tu ouvres Chrome sur localhost:5173, et tu te connectes avec le compte que je crée. »

---

## Fichiers sensibles (ne pas envoyer par email)

- `backend\.env`
- `infra\sipup\.env`
- `backend\ivr_verification.db`

Les configurer **en live** sur TeamViewer ou via un canal sécurisé.
