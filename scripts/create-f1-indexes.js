// Sélectionner la base contenant les imports avant d'exécuter ce script.
// Ex. : mongosh urbanflow scripts/create-f1-indexes.js
// Relancer ce script conserve les index existants de même nom et définition.
if (!db.getCollectionNames().includes("trips")) {
    throw new Error("Collection trips absente : vérifier la base et les imports.");
}

print(db.trips.createIndex(
    { "data.PULocationID": 1, "data.tpep_pickup_datetime": 1 },
    { name: "f1_pickup_zone_datetime" }
));
print(db.trips.createIndex(
    { "data.DOLocationID": 1, "data.tpep_dropoff_datetime": 1 },
    { name: "f1_dropoff_zone_datetime" }
));
