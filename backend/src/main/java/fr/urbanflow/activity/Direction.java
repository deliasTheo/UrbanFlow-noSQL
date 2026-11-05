package fr.urbanflow.activity;

// Les valeurs en minuscules sont aussi celles acceptées dans l'URL.
public enum Direction {
    pickup("PULocationID", "tpep_pickup_datetime"),
    dropoff("DOLocationID", "tpep_dropoff_datetime");

    final String zoneField;
    final String timeField;

    Direction(String zoneField, String timeField) {
        this.zoneField = "data." + zoneField;
        this.timeField = "data." + timeField;
    }
}
