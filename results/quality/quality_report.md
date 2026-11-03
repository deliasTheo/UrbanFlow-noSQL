# Rapport de qualité des données TLC

## Fichiers et affectation temporelle

Règle : un trajet est affecté au mois de son heure de prise en charge (heure locale).

| Fichier | Lignes | Dans le mois du fichier | Hors du mois |
|---|---:|---:|---:|
| yellow_tripdata_2024-01.parquet | 2,964,624 | 2,964,606 | 18 |
| yellow_tripdata_2024-02.parquet | 3,007,526 | 3,007,511 | 15 |
| yellow_tripdata_2024-03.parquet | 3,582,628 | 3,582,605 | 23 |
| yellow_tripdata_2024-04.parquet | 3,514,289 | 3,514,280 | 9 |
| yellow_tripdata_2024-05.parquet | 3,723,833 | 3,723,800 | 33 |
| yellow_tripdata_2024-06.parquet | 3,539,193 | 3,539,142 | 51 |

## Couverture spatiale (prises en charge par borough)

| Mois | Zones de départ | Zones d'arrivée | Bronx | Brooklyn | EWR | Manhattan | Outside of NYC | Queens | Staten Island | Unknown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024-01 | 260 | 261 | 6,905 | 25,258 | 295 | 2,646,948 | 1,658 | 273,128 | 72 | 10,360 |
| 2024-02 | 254 | 260 | 6,972 | 28,022 | 287 | 2,710,784 | 1,433 | 250,310 | 57 | 9,661 |
| 2024-03 | 259 | 260 | 11,082 | 43,939 | 372 | 3,199,034 | 2,081 | 314,448 | 105 | 11,567 |
| 2024-04 | 259 | 261 | 10,836 | 45,444 | 509 | 3,127,376 | 1,956 | 317,164 | 112 | 10,892 |
| 2024-05 | 258 | 259 | 11,930 | 53,855 | 595 | 3,296,123 | 2,183 | 347,295 | 172 | 11,680 |
| 2024-06 | 260 | 259 | 11,140 | 57,039 | 481 | 3,127,944 | 1,996 | 328,919 | 156 | 11,518 |

## Fréquence des anomalies

| Code | Description | 2024-01 | 2024-02 | 2024-03 | 2024-04 | 2024-05 | 2024-06 |
|---|---|---:|---:|---:|---:|---:|---:|
| `PICKUP_OUTSIDE_FILE_MONTH` | heure de prise en charge hors du mois du fichier | 18 (0.00 %) | 15 (0.00 %) | 23 (0.00 %) | 9 (0.00 %) | 33 (0.00 %) | 51 (0.00 %) |
| `NON_POSITIVE_DURATION` | durée nulle ou négative | 870 (0.03 %) | 803 (0.03 %) | 1,128 (0.03 %) | 1,089 (0.03 %) | 1,147 (0.03 %) | 1,140 (0.03 %) |
| `EXCESSIVE_DURATION` | durée supérieure à 6 h | 1,772 (0.06 %) | 1,736 (0.06 %) | 1,927 (0.05 %) | 1,982 (0.06 %) | 1,982 (0.05 %) | 1,950 (0.06 %) |
| `ZERO_DISTANCE` | distance nulle | 60,371 (2.04 %) | 68,225 (2.27 %) | 87,168 (2.43 %) | 45,813 (1.30 %) | 49,791 (1.34 %) | 52,954 (1.50 %) |
| `IMPLAUSIBLE_DISTANCE` | distance supérieure à 100 miles | 59 (0.00 %) | 71 (0.00 %) | 122 (0.00 %) | 150 (0.00 %) | 154 (0.00 %) | 169 (0.00 %) |
| `IMPLAUSIBLE_SPEED` | vitesse moyenne supérieure à 80 mph | 1,107 (0.04 %) | 953 (0.03 %) | 1,241 (0.03 %) | 1,141 (0.03 %) | 1,158 (0.03 %) | 1,115 (0.03 %) |
| `NEGATIVE_AMOUNT` | montant total négatif | 35,504 (1.20 %) | 36,080 (1.20 %) | 44,311 (1.24 %) | 43,749 (1.24 %) | 48,992 (1.32 %) | 48,795 (1.38 %) |
| `REVERSAL_RECORD` | écriture d'annulation : montant négatif avec un trajet d'origine identique | 30,672 (1.03 %) | 31,183 (1.04 %) | 38,391 (1.07 %) | 37,825 (1.08 %) | 42,606 (1.14 %) | 42,313 (1.20 %) |
| `REVERSED_ORIGINAL` | trajet d'origine ayant fait l'objet d'une annulation | 30,672 (1.03 %) | 31,183 (1.04 %) | 38,391 (1.07 %) | 37,825 (1.08 %) | 42,606 (1.14 %) | 42,313 (1.20 %) |
| `UNKNOWN_ZONE` | zone de départ ou d'arrivée inconnue ou hors de la ville (264/265) | 31,527 (1.06 %) | 28,974 (0.96 %) | 35,374 (0.99 %) | 35,759 (1.02 %) | 38,725 (1.04 %) | 38,513 (1.09 %) |
| `EXACT_DUPLICATE` | ligne strictement identique à une ligne précédente du même fichier | 0 (0.00 %) | 1 (0.00 %) | 0 (0.00 %) | 0 (0.00 %) | 0 (0.00 %) | 0 (0.00 %) |
| `MISSING_PASSENGER_INFO` | passenger_count, RatecodeID et suppléments absents | 140,162 (4.73 %) | 185,610 (6.17 %) | 426,190 (11.90 %) | 408,576 (11.63 %) | 404,666 (10.87 %) | 410,781 (11.61 %) |
| `DST_SPANNING` | trajet à cheval sur un changement d'heure (durée corrigée) | 0 (0.00 %) | 0 (0.00 %) | 1,153 (0.03 %) | 0 (0.00 %) | 0 (0.00 %) | 0 (0.00 %) |
| `DST_UNRESOLVED` | heure inexistante ou ambiguë à cause d'un changement d'heure | 0 (0.00 %) | 0 (0.00 %) | 3 (0.00 %) | 0 (0.00 %) | 0 (0.00 %) | 0 (0.00 %) |

## Effet du filtrage par profil

- **activity** (F1, F3 (comptages par zone et par période)) : exclut `NEGATIVE_AMOUNT`, `EXACT_DUPLICATE`
- **flows** (F2, F5 (flux origine-destination)) : exclut `NEGATIVE_AMOUNT`, `EXACT_DUPLICATE`, `UNKNOWN_ZONE`
- **journey** (F4 (durées, distances, vitesses)) : exclut `NEGATIVE_AMOUNT`, `EXACT_DUPLICATE`, `UNKNOWN_ZONE`, `NON_POSITIVE_DURATION`, `EXCESSIVE_DURATION`, `ZERO_DISTANCE`, `IMPLAUSIBLE_DISTANCE`, `IMPLAUSIBLE_SPEED`, `DST_UNRESOLVED`

| Profil | 2024-01 | 2024-02 | 2024-03 | 2024-04 | 2024-05 | 2024-06 |
|---|---:|---:|---:|---:|---:|---:|
| activity | 2,929,120 (−1.20 %) | 2,971,445 (−1.20 %) | 3,538,317 (−1.24 %) | 3,470,540 (−1.24 %) | 3,674,841 (−1.32 %) | 3,490,398 (−1.38 %) |
| flows | 2,898,055 (−2.25 %) | 2,942,952 (−2.15 %) | 3,503,542 (−2.21 %) | 3,435,410 (−2.24 %) | 3,636,771 (−2.34 %) | 3,452,592 (−2.45 %) |
| journey | 2,841,251 (−4.16 %) | 2,878,111 (−4.30 %) | 3,420,628 (−4.52 %) | 3,394,040 (−3.42 %) | 3,591,918 (−3.54 %) | 3,404,607 (−3.80 %) |

## Exemples concrets

Numéro de ligne en base 0 dans le fichier Parquet d'origine.

### `PICKUP_OUTSIDE_FILE_MONTH` — heure de prise en charge hors du mois du fichier

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 256,
    "VendorID": 2,
    "tpep_pickup_datetime": "2023-12-31 23:56:46",
    "tpep_dropoff_datetime": "2024-01-01 00:12:06",
    "passenger_count": 2.0,
    "trip_distance": 2.38,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 236,
    "DOLocationID": 142,
    "payment_type": 1,
    "fare_amount": 15.6,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 1.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 21.6,
    "congestion_surcharge": 2.5,
    "Airport_fee": 0.0,
    "duration_s": 920.0,
    "naive_duration_s": 920.0
  }
}
```

### `NON_POSITIVE_DURATION` — durée nulle ou négative

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 87994,
    "VendorID": 1,
    "tpep_pickup_datetime": "2024-01-02 10:00:00",
    "tpep_dropoff_datetime": "2024-01-02 09:53:56",
    "passenger_count": 1.0,
    "trip_distance": 7.2,
    "RatecodeID": 99.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 75,
    "DOLocationID": 95,
    "payment_type": 1,
    "fare_amount": 38.5,
    "extra": 0.0,
    "mta_tax": 0.5,
    "tip_amount": 0.0,
    "tolls_amount": 6.94,
    "improvement_surcharge": 1.0,
    "total_amount": 46.94,
    "congestion_surcharge": 0.0,
    "Airport_fee": 0.0,
    "duration_s": -364.0,
    "naive_duration_s": -364.0
  }
}
```

### `EXCESSIVE_DURATION` — durée supérieure à 6 h

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 3992,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-01-01 00:39:11",
    "tpep_dropoff_datetime": "2024-01-02 00:34:19",
    "passenger_count": 5.0,
    "trip_distance": 2.75,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 43,
    "DOLocationID": 137,
    "payment_type": 1,
    "fare_amount": 17.7,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 5.68,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 28.38,
    "congestion_surcharge": 2.5,
    "Airport_fee": 0.0,
    "duration_s": 86108.0,
    "naive_duration_s": 86108.0
  }
}
```

### `ZERO_DISTANCE` — distance nulle

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 17,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-01-01 00:52:09",
    "tpep_dropoff_datetime": "2024-01-01 00:52:28",
    "passenger_count": 1.0,
    "trip_distance": 0.0,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 237,
    "DOLocationID": 237,
    "payment_type": 2,
    "fare_amount": 3.0,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 0.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 8.0,
    "congestion_surcharge": 2.5,
    "Airport_fee": 0.0,
    "duration_s": 19.0,
    "naive_duration_s": 19.0
  }
}
```

### `IMPLAUSIBLE_DISTANCE` — distance supérieure à 100 miles

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 71811,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-01-02 02:38:04",
    "tpep_dropoff_datetime": "2024-01-02 04:38:30",
    "passenger_count": 1.0,
    "trip_distance": 101.28,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 144,
    "DOLocationID": 265,
    "payment_type": 2,
    "fare_amount": 359.3,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 0.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 364.3,
    "congestion_surcharge": 2.5,
    "Airport_fee": 0.0,
    "duration_s": 7226.0,
    "naive_duration_s": 7226.0
  }
}
```

### `IMPLAUSIBLE_SPEED` — vitesse moyenne supérieure à 80 mph

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 221,
    "VendorID": 1,
    "tpep_pickup_datetime": "2024-01-01 00:26:02",
    "tpep_dropoff_datetime": "2024-01-01 00:26:21",
    "passenger_count": 1.0,
    "trip_distance": 2.3,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 42,
    "DOLocationID": 42,
    "payment_type": 1,
    "fare_amount": 3.0,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 10.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 15.5,
    "congestion_surcharge": 0.0,
    "Airport_fee": 0.0,
    "duration_s": 19.0,
    "naive_duration_s": 19.0
  }
}
```

### `NEGATIVE_AMOUNT` — montant total négatif

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 99,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-01-01 00:18:24",
    "tpep_dropoff_datetime": "2024-01-01 00:30:39",
    "passenger_count": 1.0,
    "trip_distance": 2.16,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 249,
    "DOLocationID": 232,
    "payment_type": 4,
    "fare_amount": -13.5,
    "extra": -1.0,
    "mta_tax": -0.5,
    "tip_amount": 0.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": -1.0,
    "total_amount": -18.5,
    "congestion_surcharge": -2.5,
    "Airport_fee": 0.0,
    "duration_s": 735.0,
    "naive_duration_s": 735.0
  }
}
```

### `REVERSAL_RECORD` — écriture d'annulation : montant négatif avec un trajet d'origine identique

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 99,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-01-01 00:18:24",
    "tpep_dropoff_datetime": "2024-01-01 00:30:39",
    "passenger_count": 1.0,
    "trip_distance": 2.16,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 249,
    "DOLocationID": 232,
    "payment_type": 4,
    "fare_amount": -13.5,
    "extra": -1.0,
    "mta_tax": -0.5,
    "tip_amount": 0.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": -1.0,
    "total_amount": -18.5,
    "congestion_surcharge": -2.5,
    "Airport_fee": 0.0,
    "duration_s": 735.0,
    "naive_duration_s": 735.0
  },
  "paired_rows": [
    {
      "row_number": 100,
      "VendorID": 2,
      "tpep_pickup_datetime": "2024-01-01 00:18:24",
      "tpep_dropoff_datetime": "2024-01-01 00:30:39",
      "passenger_count": 1.0,
      "trip_distance": 2.16,
      "RatecodeID": 1.0,
      "store_and_fwd_flag": "N",
      "PULocationID": 249,
      "DOLocationID": 232,
      "payment_type": 4,
      "fare_amount": 13.5,
      "extra": 1.0,
      "mta_tax": 0.5,
      "tip_amount": 0.0,
      "tolls_amount": 0.0,
      "improvement_surcharge": 1.0,
      "total_amount": 18.5,
      "congestion_surcharge": 2.5,
      "Airport_fee": 0.0,
      "duration_s": 735.0,
      "naive_duration_s": 735.0
    }
  ]
}
```

### `REVERSED_ORIGINAL` — trajet d'origine ayant fait l'objet d'une annulation

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 100,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-01-01 00:18:24",
    "tpep_dropoff_datetime": "2024-01-01 00:30:39",
    "passenger_count": 1.0,
    "trip_distance": 2.16,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 249,
    "DOLocationID": 232,
    "payment_type": 4,
    "fare_amount": 13.5,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 0.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 18.5,
    "congestion_surcharge": 2.5,
    "Airport_fee": 0.0,
    "duration_s": 735.0,
    "naive_duration_s": 735.0
  },
  "paired_rows": [
    {
      "row_number": 99,
      "VendorID": 2,
      "tpep_pickup_datetime": "2024-01-01 00:18:24",
      "tpep_dropoff_datetime": "2024-01-01 00:30:39",
      "passenger_count": 1.0,
      "trip_distance": 2.16,
      "RatecodeID": 1.0,
      "store_and_fwd_flag": "N",
      "PULocationID": 249,
      "DOLocationID": 232,
      "payment_type": 4,
      "fare_amount": -13.5,
      "extra": -1.0,
      "mta_tax": -0.5,
      "tip_amount": 0.0,
      "tolls_amount": 0.0,
      "improvement_surcharge": -1.0,
      "total_amount": -18.5,
      "congestion_surcharge": -2.5,
      "Airport_fee": 0.0,
      "duration_s": 735.0,
      "naive_duration_s": 735.0
    }
  ]
}
```

### `UNKNOWN_ZONE` — zone de départ ou d'arrivée inconnue ou hors de la ville (264/265)

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 24,
    "VendorID": 1,
    "tpep_pickup_datetime": "2024-01-01 00:42:05",
    "tpep_dropoff_datetime": "2024-01-01 01:16:49",
    "passenger_count": 1.0,
    "trip_distance": 23.9,
    "RatecodeID": 5.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 263,
    "DOLocationID": 265,
    "payment_type": 1,
    "fare_amount": 120.0,
    "extra": 0.0,
    "mta_tax": 0.0,
    "tip_amount": 0.0,
    "tolls_amount": 6.94,
    "improvement_surcharge": 1.0,
    "total_amount": 127.94,
    "congestion_surcharge": 0.0,
    "Airport_fee": 0.0,
    "duration_s": 2084.0,
    "naive_duration_s": 2084.0
  }
}
```

### `EXACT_DUPLICATE` — ligne strictement identique à une ligne précédente du même fichier

Fichier `yellow_tripdata_2024-02.parquet` :

```json
{
  "record": {
    "row_number": 754252,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-02-08 18:23:50",
    "tpep_dropoff_datetime": "2024-02-08 18:38:14",
    "passenger_count": 1.0,
    "trip_distance": 0.81,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 162,
    "DOLocationID": 230,
    "payment_type": 1,
    "fare_amount": 12.8,
    "extra": 2.5,
    "mta_tax": 0.5,
    "tip_amount": 3.86,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 23.16,
    "congestion_surcharge": 2.5,
    "Airport_fee": 0.0,
    "duration_s": 864.0,
    "naive_duration_s": 864.0
  }
}
```

### `MISSING_PASSENGER_INFO` — passenger_count, RatecodeID et suppléments absents

Fichier `yellow_tripdata_2024-01.parquet` :

```json
{
  "record": {
    "row_number": 2824462,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-01-01 00:34:19",
    "tpep_dropoff_datetime": "2024-01-01 00:51:22",
    "passenger_count": null,
    "trip_distance": 2.04,
    "RatecodeID": null,
    "store_and_fwd_flag": null,
    "PULocationID": 143,
    "DOLocationID": 141,
    "payment_type": 0,
    "fare_amount": 12.72,
    "extra": 0.0,
    "mta_tax": 0.5,
    "tip_amount": 0.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 16.72,
    "congestion_surcharge": null,
    "Airport_fee": null,
    "duration_s": 1023.0,
    "naive_duration_s": 1023.0
  }
}
```

### `DST_SPANNING` — trajet à cheval sur un changement d'heure (durée corrigée)

Fichier `yellow_tripdata_2024-03.parquet` :

```json
{
  "record": {
    "row_number": 942762,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-03-09 23:38:43",
    "tpep_dropoff_datetime": "2024-03-10 03:40:14",
    "passenger_count": 1.0,
    "trip_distance": 31.35,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 249,
    "DOLocationID": 203,
    "payment_type": 2,
    "fare_amount": 119.2,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 0.0,
    "tolls_amount": 6.94,
    "improvement_surcharge": 1.0,
    "total_amount": 131.14,
    "congestion_surcharge": 2.5,
    "Airport_fee": 0.0,
    "duration_s": 10891.0,
    "naive_duration_s": 14491.0
  }
}
```

### `DST_UNRESOLVED` — heure inexistante ou ambiguë à cause d'un changement d'heure

Fichier `yellow_tripdata_2024-03.parquet` :

```json
{
  "record": {
    "row_number": 841170,
    "VendorID": 2,
    "tpep_pickup_datetime": "2024-03-09 02:31:02",
    "tpep_dropoff_datetime": "2024-03-10 02:09:54",
    "passenger_count": 1.0,
    "trip_distance": 3.36,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 114,
    "DOLocationID": 48,
    "payment_type": 1,
    "fare_amount": 19.1,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 3.62,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 27.72,
    "congestion_surcharge": 2.5,
    "Airport_fee": 0.0,
    "duration_s": 85132.0,
    "naive_duration_s": 85132.0
  }
}
```

