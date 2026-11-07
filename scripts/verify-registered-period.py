"""Recalcule des résultats de l'API depuis les Parquet d'origine, sans lire MongoDB.

Complète les scripts verify-f2 à verify-f5, qui ne couvrent que janvier :
ici la base contient les six mois et on vérifie sur la période enregistrée.

  F1 : zone 181 à l'arrivée sur le semestre
  F2 : Brooklyn de janvier à mars
  F4 : JFK vers Midtown, autour du changement d'heure du 10 mars
  F6 : les trajets d'avril sont bien visibles

Usage (API lancée sur le port 8090, sur n'importe quel déploiement) :
    python scripts/verify-registered-period.py
"""

import json

import common
import numpy as np
import pandas as pd

UNKNOWN_ZONES = [264, 265]
MONTHS = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
KEPT_COLUMNS = ["PULocationID", "DOLocationID", "tpep_pickup_datetime", "tpep_dropoff_datetime",
                "trip_distance", "total_amount", "duplicate"]


def read_all_months():
    frames = []
    for month in MONTHS:
        frame = pd.read_parquet(common.ROOT / f"data/raw/yellow_tripdata_{month}.parquet")
        # Les doublons se cherchent sur toutes les colonnes, avant d'en retirer.
        frame["duplicate"] = frame.duplicated()
        frames.append(frame[KEPT_COLUMNS])
    return pd.concat(frames, ignore_index=True)


def api_json(path):
    status, _, body = common.call_api(path)
    assert status == 200, body
    return json.loads(body)


def counts(frame, kept):
    retained = int(kept[frame.index].sum())
    return {"raw": len(frame), "retained": retained, "excluded": len(frame) - retained}


def check_f1(trips, activity):
    path = common.REQUESTS["f1_parkslope_dropoff_semester"]
    selected = trips[(trips.DOLocationID == 181)
                     & (trips.tpep_dropoff_datetime >= "2024-01-01")
                     & (trips.tpep_dropoff_datetime < "2024-07-01")]
    response = api_json(path)
    assert response["totals"] == counts(selected, activity)
    by_hour = selected[activity[selected.index]].groupby(selected.tpep_dropoff_datetime.dt.hour).size()
    for bucket in response["byHour"]:
        assert bucket["counts"]["retained"] == int(by_hour.get(bucket["value"], 0))
    return response["totals"]


def check_f2(trips, flows, brooklyn):
    response = api_json(common.REQUESTS["f2_brooklyn_quarter"])
    outgoing = trips[trips.PULocationID.isin(brooklyn)
                     & (trips.tpep_pickup_datetime >= "2024-01-01")
                     & (trips.tpep_pickup_datetime < "2024-04-01")]
    assert response["totals"] == counts(outgoing, flows)
    grouped = outgoing[flows[outgoing.index]].groupby(["PULocationID", "DOLocationID"]).size()
    expected = sorted(
        [(int(o), int(d), int(n)) for (o, d), n in grouped.items() if n >= 20],
        key=lambda pair: (-pair[2], pair[0], pair[1]))
    found = [(p["origin"]["id"], p["destination"]["id"], p["counts"]["retained"]) for p in response["pairs"]]
    assert found == expected[:len(found)]
    assert response["eligiblePairs"] == len(expected)
    return {"totals": response["totals"], "top": found[:3]}


def check_f4(trips, activity):
    """Durées via UTC : le service doit faire pareil, sinon le 10 mars serait faux d'une heure."""
    response = api_json(common.REQUESTS["f4_jfk_midtown"])
    pair = trips[(trips.PULocationID == 132) & (trips.DOLocationID == 161)]
    pickup = pair.tpep_pickup_datetime.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    dropoff = pair.tpep_dropoff_datetime.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    duration = (dropoff - pickup).dt.total_seconds()
    distance = pair.trip_distance
    speed = distance / (duration / 3600)
    good = (activity[pair.index] & duration.notna() & (duration > 0) & (duration <= 6 * 3600)
            & (distance > 0) & (distance <= 100) & ~((duration > 0) & (speed > 80)))

    results = {}
    for label, start, end in [("reference", "2024-02-12", "2024-03-04"), ("current", "2024-03-11", "2024-04-01")]:
        in_period = (pair.tpep_pickup_datetime >= start) & (pair.tpep_pickup_datetime < end)
        values = duration[in_period & good]
        usable = response[label]["usable"]
        assert usable["records"] == len(values)
        assert np.isclose(usable["durationSeconds"]["median"], np.median(values))
        assert np.isclose(usable["durationSeconds"]["p90"], np.quantile(values, 0.9))
        results[label] = {"trips": len(values), "median_seconds": float(np.median(values))}
    return results


def check_april_is_visible(trips, activity):
    response = api_json("/api/activity?zoneId=181&direction=pickup&from=2024-04-01&to=2024-05-01")
    selected = trips[(trips.PULocationID == 181)
                     & (trips.tpep_pickup_datetime >= "2024-04-01")
                     & (trips.tpep_pickup_datetime < "2024-05-01")]
    assert response["totals"] == counts(selected, activity)
    return response["totals"]


def main():
    zones = pd.read_csv(common.ROOT / "data/raw/taxi_zone_lookup.csv")
    brooklyn = zones.loc[zones.Borough == "Brooklyn", "LocationID"].tolist()

    trips = read_all_months()
    print("Lignes lues :", len(trips), flush=True)
    activity = ~((trips.total_amount < 0) | trips.duplicate)
    flows = activity & ~(trips.PULocationID.isin(UNKNOWN_ZONES) | trips.DOLocationID.isin(UNKNOWN_ZONES))

    report = {
        "source_rows": len(trips),
        "f1": check_f1(trips, activity),
        "f2": check_f2(trips, flows, brooklyn),
        "f4": check_f4(trips, activity),
        "f6_avril": check_april_is_visible(trips, activity),
        "verified": True,
    }
    common.write_json(common.RESULTS / "verification" / "registered-period.json", report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
