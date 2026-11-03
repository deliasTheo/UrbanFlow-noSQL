"""Téléchargement des fichiers TLC et tenue du manifeste de provenance.

Pour chaque fichier source, le manifeste (data/manifest.json) conserve
l'URL, la date de récupération, la taille, l'empreinte SHA-256 et, pour les
fichiers de trajets, le nombre de lignes lu dans les métadonnées Parquet.

Un fichier déjà présent n'est pas re-téléchargé (sauf --force) : son
empreinte est recalculée et comparée à celle du manifeste, ce qui permet de
détecter une modification locale ou une nouvelle version publiée par la TLC.

Usage :
    python -m urbanflow.download                       # mois d'étude, de mise à jour et d'expérience
    python -m urbanflow.download --months 2024-07
"""

import argparse
import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from urbanflow import config

CHUNK_SIZE = 1 << 20  # 1 Mio


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, dest: Path) -> None:
    """Télécharge `url` vers `dest` en passant par un fichier temporaire.

    Le renommage final évite de laisser un fichier tronqué sous le nom
    définitif si le transfert est interrompu.
    """
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, tmp.open("wb") as out:
        shutil.copyfileobj(response, out, CHUNK_SIZE)
    tmp.replace(dest)


def load_manifest() -> dict:
    if config.MANIFEST_PATH.exists():
        return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"files": {}}


def save_manifest(manifest: dict) -> None:
    manifest["files"] = dict(sorted(manifest["files"].items()))
    config.MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def register(manifest: dict, name: str, url: str, force: bool) -> dict:
    """Garantit la présence locale d'un fichier et met à jour son entrée."""
    path = config.RAW_DIR / name
    previous = manifest["files"].get(name)

    downloaded = False
    if force or not path.exists():
        fetch(url, path)
        downloaded = True

    checksum = sha256_of(path)
    if previous and previous["sha256"] != checksum and not downloaded:
        raise RuntimeError(
            f"{name} : l'empreinte locale ne correspond plus au manifeste "
            f"({checksum[:12]}… au lieu de {previous['sha256'][:12]}…)"
        )

    # La date de récupération n'est conservée que si le contenu est inchangé.
    if previous and previous["sha256"] == checksum:
        retrieved_at = previous["retrieved_at"]
    else:
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    entry = {
        "url": url,
        "retrieved_at": retrieved_at,
        "size_bytes": path.stat().st_size,
        "sha256": checksum,
    }
    if path.suffix == ".parquet":
        entry["num_rows"] = pq.ParquetFile(path).metadata.num_rows

    manifest["files"][name] = entry
    status = "téléchargé" if downloaded else "déjà présent"
    print(f"{name:40s} {status:13s} {entry['size_bytes'] / 1e6:7.1f} Mo  sha256={checksum[:12]}…")
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--months", nargs="+",
        default=config.STUDY_MONTHS + [config.UPDATE_MONTH] + config.EXPERIMENT_MONTHS,
        help="mois à récupérer, au format AAAA-MM",
    )
    parser.add_argument("--force", action="store_true", help="re-télécharger même si le fichier existe")
    args = parser.parse_args()

    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    register(manifest, config.ZONE_LOOKUP_FILE, config.ZONE_LOOKUP_URL, args.force)
    for month in args.months:
        name = config.trip_file_name(month)
        register(manifest, name, config.TRIP_URL_TEMPLATE.format(month=month), args.force)

    save_manifest(manifest)
    print(f"Manifeste écrit dans {config.MANIFEST_PATH.relative_to(config.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
