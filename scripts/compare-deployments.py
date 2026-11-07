"""Vérifie que le local et les deux clusters donnent les mêmes résultats.

Lit les réponses gardées par e2-deployments.py. Les listes sont déjà triées par
les services, avec les identifiants pour départager les ex æquo : on garde donc
leur ordre, et on trie seulement les clés des objets. Le moindre écart de valeur
ou de classement fait échouer la comparaison.

Usage :
    python scripts/compare-deployments.py
"""

import hashlib
import json
import sys

import common

REFERENCE = "local"
OTHERS = ["zone", "month"]


def canonical(body):
    return json.dumps(json.loads(body), sort_keys=True, ensure_ascii=False)


def first_difference(a, b, path=""):
    """Chemin de la première valeur différente, pour comprendre un échec."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}/{key}: clé absente"
            found = first_difference(a[key], b[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} éléments contre {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else f"{path}: {a} contre {b}"


def read_response(deployment, name):
    path = common.ROOT / "data/staging/responses" / deployment / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(deployment):
    path = common.RESULTS / "distributed" / "fingerprints" / f"{deployment}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    folder = common.ROOT / "data/staging/responses" / REFERENCE
    names = sorted(path.stem for path in folder.glob("*.json"))
    results = []
    failures = 0

    same_data = all(fingerprint(other) == fingerprint(REFERENCE) for other in OTHERS)
    print("Mêmes trajets partout :", same_data)
    if not same_data:
        failures += 1

    for name in names:
        reference = read_response(REFERENCE, name)
        row = {"request": name, "status": reference["status"]}
        if reference["status"] != 200:
            failures += 1
            row["error"] = reference["body"][:200]
        else:
            row["sha256"] = hashlib.sha256(canonical(reference["body"]).encode("utf-8")).hexdigest()
        for other in OTHERS:
            response = read_response(other, name)
            if response["status"] != reference["status"]:
                row[other] = f"code HTTP {response['status']}"
                failures += 1
            elif reference["status"] != 200:
                row[other] = "même erreur"
            elif canonical(response["body"]) == canonical(reference["body"]):
                row[other] = "identique"
            else:
                row[other] = first_difference(json.loads(reference["body"]), json.loads(response["body"]))
                failures += 1
        results.append(row)
        print(name, row["status"], row["zone"], "|", row["month"])

    common.write_json(common.RESULTS / "distributed" / "comparison.json", {
        "same_trips_everywhere": same_data,
        "failures": failures,
        "requests": results,
    })
    print(f"{len(names)} requêtes, {failures} écart(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
