// Base contenant les imports, sélectionnée dans mongosh avant exécution.
if (!db.getCollectionNames().includes("trips")) {
    throw new Error("Collection trips absente : vérifier la base et les imports.");
}
print(db.trips.createIndex(
    { "data.PULocationID": 1, "data.DOLocationID": 1, "data.tpep_pickup_datetime": 1 },
    { name: "f4_pair_pickup_datetime" }
));
