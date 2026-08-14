"""Publication GitHub : repo, Pages, branche gh-pages, workflow.

Fonctionne à l'identique en local (identifiants git/gh de l'utilisateur)
et dans GitHub Actions (GITHUB_TOKEN persisté par actions/checkout).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "daily.yml"
PUBLISH_DIR = ROOT / ".publish"


def sh(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Exécute une commande, retourne sa sortie ( échec → CalledProcessError )."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Échec : {' '.join(cmd)}\n{proc.stdout.strip()}\n{proc.stderr.strip()}"
        )
    return proc.stdout.strip()


# ---------------------------------------------------------------- livraison --

def cron_for(delivery_hour: str, *, now: datetime | None = None) -> str:
    """Convertit une heure Paris (« 07:30 ») en cron UTC « 30 5 * * * »."""
    now = now or datetime.now(tz=PARIS)
    hh, mm = (int(part) for part in delivery_hour.split(":"))
    paris_time = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    utc_time = paris_time.astimezone(timezone.utc)
    return f"{utc_time.minute} {utc_time.hour} * * *"


def update_workflow_cron(delivery_hour: str, path: Path = WORKFLOW_PATH) -> None:
    """Réécrit la ligne cron du workflow avec l'heure de livraison choisie."""
    content = path.read_text(encoding="utf-8")
    new_cron = cron_for(delivery_hour)
    updated, count = re.subn(r'- cron: "[^"]*"', f'- cron: "{new_cron}"', content, count=1)
    if count:
        path.write_text(updated, encoding="utf-8")


def fetch_existing(dist_dir: Path) -> None:
    """Récupère les métadonnées d'épisodes et l'historique publiés sur gh-pages.

    Permet de reconstruire un flux complet (tous les épisodes) et d'éviter
    de rediffuser des articles déjà traités les jours précédents.
    """
    import json

    try:
        sh(["git", "fetch", "origin", "gh-pages", "--depth=1"])
    except RuntimeError:
        return  # branche pas encore publiée : premier épisode

    listing = sh(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD"])
    for blob in listing.splitlines():
        if blob.startswith("episodes/") and blob.endswith(".json"):
            target = dist_dir / blob
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(sh(["git", "show", f"FETCH_HEAD:{blob}"]), encoding="utf-8")
        elif blob == "seen.json":
            remote = set(json.loads(sh(["git", "show", "FETCH_HEAD:seen.json"])))
            local_file = dist_dir / "seen.json"
            local = set()
            if local_file.exists():
                try:
                    local = set(json.loads(local_file.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    local = set()
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_text(
                json.dumps(sorted(remote | local), ensure_ascii=False), encoding="utf-8"
            )


def publish_dist(dist_dir: Path | None = None, message: str = "nouvel épisode") -> None:
    """Publie le contenu de dist/ sur la branche gh-pages (sans rien y supprimer)."""
    dist_dir = dist_dir or ROOT / "dist"
    if not dist_dir.exists():
        raise RuntimeError("Rien à publier : dist/ est absent.")

    if PUBLISH_DIR.exists():
        sh(["git", "worktree", "remove", "--force", str(PUBLISH_DIR)])

    has_remote_branch = bool(sh(["git", "ls-remote", "--heads", "origin", "gh-pages"]))
    if has_remote_branch:
        sh(["git", "fetch", "origin", "gh-pages"])
        sh(["git", "worktree", "add", "--detach", str(PUBLISH_DIR), "origin/gh-pages"])
    else:
        # Premier déploiement : branche orpheline vide
        sh(["git", "worktree", "add", "--detach", str(PUBLISH_DIR)])
        sh(["git", "checkout", "--orphan", "gh-pages"], cwd=PUBLISH_DIR)
        sh(["git", "rm", "-rf", "."], cwd=PUBLISH_DIR, check=False)
        sh(["git", "clean", "-xfd"], cwd=PUBLISH_DIR)

    # Copie du contenu généré (les anciens épisodes présents sur gh-pages sont conservés)
    for item in dist_dir.iterdir():
        target = PUBLISH_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)

    sh(["git", "add", "-A"], cwd=PUBLISH_DIR)
    status = sh(["git", "status", "--porcelain"], cwd=PUBLISH_DIR)
    if status:
        sh(["git", "commit", "-m", message], cwd=PUBLISH_DIR)
        sh(["git", "push", "origin", "HEAD:gh-pages"], cwd=PUBLISH_DIR)
    sh(["git", "worktree", "remove", "--force", str(PUBLISH_DIR)])


# ------------------------------------------------------------------- GitHub --

def remote_slug() -> str | None:
    """« owner/repo » depuis l'remote origin (None si pas de repo GitHub)."""
    url = sh(["git", "remote", "get-url", "origin"], check=False)
    if not url:
        return None
    match = re.search(r"github\.com[/:]([^/]+)/([^/.]+)(?:\.git)?$", url)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    try:  # dernier recours : gh connaît le repo
        return sh(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    except RuntimeError:
        return None


def pages_base_for(slug: str) -> str:
    """URL racine GitHub Pages attendue pour ce repo."""
    owner, repo = slug.split("/")
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{repo}/"


def current_branch() -> str:
    return sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def push_config(config_path: Path) -> None:
    """Committe config + workflow + assets et pousse la branche courante."""
    files = [str(config_path), str(WORKFLOW_PATH)]
    assets = ROOT / "assets"
    if assets.exists():
        files.append(str(assets))
    sh(["git", "add", *files])
    status = sh(["git", "status", "--porcelain"])
    if status:
        sh(["git", "commit", "-m", "réglages : mise à jour du podcast"])
        sh(["git", "push", "origin", current_branch()])


def setup_repo(name: str, *, private: bool, slug: str | None = None) -> str:
    """Crée le repo GitHub (si besoin) et pousse le code. Retourne « owner/repo »."""
    if not slug:
        visibility = "--private" if private else "--public"
        sh(["gh", "repo", "create", name, visibility, "--source", ".", "--push"])
    slug = slug or remote_slug()
    if not slug:
        raise RuntimeError("Impossible de déterminer le repo GitHub.")
    sh(["git", "push", "-u", "origin", current_branch()], check=False)
    return slug


def enable_pages(slug: str) -> str:
    """Active GitHub Pages sur la branche gh-pages. Retourne l'URL du site."""
    current = sh(["gh", "api", f"repos/{slug}/pages"], check=False)
    if current:
        if '"branch": "gh-pages"' in current:
            return pages_base_for(slug)
        # Pages activé sur autre chose : on le repositionne
        sh(
            ["gh", "api", "-X", "PUT", f"repos/{slug}/pages",
             "-f", "source[branch]=gh-pages", "-f", "source[path]=/"]
        )
        return pages_base_for(slug)
    sh(
        ["gh", "api", "-X", "POST", f"repos/{slug}/pages",
         "-f", "source[branch]=gh-pages", "-f", "source[path]=/"]
    )
    return pages_base_for(slug)


def trigger_workflow() -> None:
    """Déclenche manuellement la génération quotidienne (workflow_dispatch)."""
    sh(["gh", "workflow", "run", "daily.yml"])
