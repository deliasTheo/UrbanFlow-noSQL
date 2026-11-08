"""Vérification indépendante F2 sur janvier complet, sans lire MongoDB.
API lancée sur la base contenant uniquement janvier complet.
"""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error
import pandas as pd

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--api', default='http://127.0.0.1:8081')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
frame = pd.read_parquet(root / 'data/raw/yellow_tripdata_2024-01.parquet')

# Recalcul direct depuis les colonnes originales, sans utiliser les flags MongoDB.
frame['retained'] = ~(
    (frame.total_amount < 0)
    | frame.duplicated()
    | frame.PULocationID.isin([264, 265])
    | frame.DOLocationID.isin([264, 265])
)
frame = frame[
    (frame.tpep_pickup_datetime >= pd.Timestamp('2024-01-01'))
    & (frame.tpep_pickup_datetime < pd.Timestamp('2024-02-01'))
].copy()
# Une semaine commence le lundi : on enlève le numéro du jour à la date.
frame['week'] = (
    frame.tpep_pickup_datetime.dt.normalize()
    - pd.to_timedelta(frame.tpep_pickup_datetime.dt.weekday, unit='D')
).dt.strftime('%Y-%m-%d')
zones = pd.read_csv(root / 'data/raw/taxi_zone_lookup.csv')

checks = []
for scope, zone_ids in [
    ('zoneIds=181', [181]),
    ('borough=Brooklyn', zones.loc[zones.Borough == 'Brooklyn', 'LocationID'].tolist()),
]:
    url = f'{args.api}/api/flows?{scope}&from=2024-01-01&to=2024-02-01'
    with urllib.request.urlopen(url, timeout=150) as reply:
        response = json.load(reply)
    outgoing = frame[frame.PULocationID.isin(zone_ids)]

    def counts(trips):
        return dict(raw=len(trips), retained=int(trips.retained.sum()), excluded=len(trips) - int(trips.retained.sum()))

    assert response['totals'] == counts(outgoing)

    # Classement attendu des paires : au moins 20 trajets, ex æquo départagés par identifiants.
    grouped = outgoing.groupby(['PULocationID', 'DOLocationID']).retained.sum()
    expected = sorted(
        [(int(origin), int(destination), int(total)) for (origin, destination), total in grouped.items() if total >= 20],
        key=lambda pair: (-pair[2], pair[0], pair[1]),
    )
    assert [(pair['origin']['id'], pair['destination']['id'], pair['counts']['retained'])
            for pair in response['pairs']] == expected[:10]
    assert response['eligiblePairs'] == len(expected)

    for flow in response['pairs']:
        origin, destination = flow['origin']['id'], flow['destination']['id']
        pair_trips = outgoing[(outgoing.PULocationID == origin) & (outgoing.DOLocationID == destination)]
        assert flow['counts'] == counts(pair_trips)

        # Sens opposé. Pour un trajet interne à une zone, il n'y a pas de retour à comparer.
        reverse = frame[(frame.PULocationID == destination) & (frame.DOLocationID == origin)]
        assert flow['reverseRetained'] == (None if origin == destination else int(reverse.retained.sum()))
        assert (sum(source['counts']['retained'] for source in flow['reverseSources'])
                == (0 if origin == destination else int(reverse.retained.sum())))
        assert abs(flow['share'] - pair_trips.retained.sum() / outgoing.retained.sum()) < 1e-12

        for week in flow['weeks']:
            assert week['counts'] == counts(pair_trips[pair_trips.week == week['start']])
        assert sum(source['counts']['raw'] for source in flow['sources']) == len(pair_trips)

        # Même classification que le service : régulier, pic, variable ou historique trop court.
        full_weeks = [week for week in flow['weeks'] if week['completeWeek']]
        values = [int(pair_trips.loc[pair_trips.week == week['start'], 'retained'].sum()) for week in full_weeks]
        qualifying = sum(value >= 5 for value in values)
        peak_share = max(values) / sum(values) if sum(values) else None
        pattern = (
            'insufficient_history' if len(values) < 3
            else 'regular' if qualifying / len(values) >= 0.75
            else 'peak' if peak_share is not None and max(values) >= 5 and peak_share >= 0.5
            else 'variable'
        )
        assert flow['referenceWeeks'] == len(values) and flow['qualifyingWeeks'] == qualifying
        assert flow['peakWeekShare'] == peak_share and flow['pattern'] == pattern

    destinations = outgoing.groupby('DOLocationID').retained.sum()
    expected_destinations = sorted(
        [(int(zone), int(total)) for zone, total in destinations.items() if total >= 20],
        key=lambda item: (-item[1], item[0]),
    )
    assert [(entry['zone']['id'], entry['counts']['retained'])
            for entry in response['destinations']] == expected_destinations[:10]
    for entry in response['destinations']:
        assert sum(source['counts']['retained'] for source in entry['sources']) == entry['counts']['retained']
    checks.append({'scope': scope, 'totals': response['totals'], 'eligiblePairs': response['eligiblePairs'], 'top': expected[:3]})

# Cas de validation de l'API, sans modification de la base.
for query, status in [
    ('zoneIds=181&borough=Brooklyn&from=2024-01-01&to=2024-02-01', 400),
    ('zoneIds=9999&from=2024-01-01&to=2024-02-01', 404),
    ('zoneIds=181&from=2024-01-01&to=2024-02-01&regularFraction=NaN', 400),
    ('zoneIds=181&from=2024-02-01&to=2024-01-01', 400),
    ('from=2024-01-01&to=2024-02-01', 400),
]:
    try:
        urllib.request.urlopen(args.api + '/api/flows?' + query)
        raise AssertionError('Erreur attendue : ' + query)
    except urllib.error.HTTPError as error:
        assert error.code == status

# Moins de trois semaines complètes : aucun flux ne doit être classé.
for query in ['zoneIds=181,189&from=2024-01-01&to=2024-01-15', 'zoneIds=181&from=2024-01-01&to=2024-02-02']:
    with urllib.request.urlopen(args.api + '/api/flows?' + query) as reply:
        data = json.load(reply)
    assert all(pair['pattern'] == 'insufficient_history' for pair in data['pairs'])

print(json.dumps({'verified': True, 'sourceRows': 2964624, 'checks': checks}, indent=2))
