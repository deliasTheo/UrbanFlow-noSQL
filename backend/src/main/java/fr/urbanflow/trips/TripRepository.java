package fr.urbanflow.trips;

import java.time.Duration;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import org.bson.Document;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.aggregation.Aggregation;
import org.springframework.data.mongodb.core.aggregation.AggregationOperation;
import org.springframework.data.mongodb.core.aggregation.AggregationOptions;
import org.springframework.stereotype.Repository;

@Repository
public class TripRepository {
    private final MongoTemplate mongo;

    public TripRepository(MongoTemplate mongo) {
        this.mongo = mongo;
    }

    // Les lignes visées par un résultat : zones, intervalle, créneau et fichiers complets.
    public record Selection(Integer pickupZoneId, Integer dropoffZoneId, String timeField, LocalDate from, LocalDate to,
            int startHour, int endHour, List<String> files) {}

    private static Document match(Selection selection) {
        var match = new Document("source.file_id", new Document("$in", selection.files()))
                .append(selection.timeField(), new Document("$gte", selection.from() + "T00:00:00")
                        .append("$lt", selection.to() + "T00:00:00"));
        if (selection.pickupZoneId() != null) {
            match.append("data.PULocationID", selection.pickupZoneId());
        }
        if (selection.dropoffZoneId() != null) {
            match.append("data.DOLocationID", selection.dropoffZoneId());
        }
        if (selection.startHour() != 0 || selection.endHour() != 24) {
            var hour = new Document("$toInt", new Document("$substrBytes", List.of("$" + selection.timeField(), 11, 2)));
            match.append("$expr", new Document("$and", List.of(
                    new Document("$gte", List.of(hour, selection.startHour())),
                    new Document("$lt", List.of(hour, selection.endHour())))));
        }
        return match;
    }

    // Lignes brutes et retenues de chaque fichier, avec le même calcul que les services.
    public List<Document> countsBySource(Selection selection, List<String> excludedFlags) {
        var retained = new Document("$eq", List.of(new Document("$size", new Document("$setIntersection", List.of(
                new Document("$ifNull", List.of("$quality_flags", List.of())), excludedFlags))), 0));
        return run(List.of(
                new Document("$match", match(selection)),
                new Document("$project", new Document("source", "$source.file_id").append("retained", retained)),
                new Document("$group", new Document("_id", "$source")
                        .append("raw", new Document("$sum", 1))
                        .append("retained", new Document("$sum", new Document("$cond", List.of("$retained", 1, 0)))))));
    }

    // Les lignes elles-mêmes. Trier par date puis par identité donne le même ordre sur tous les déploiements.
    public List<Document> trips(Selection selection, Document qualityFilter, int offset, int limit) {
        return run(List.of(
                new Document("$match", match(selection)),
                new Document("$match", qualityFilter),
                new Document("$sort", new Document(selection.timeField(), 1).append("_id", 1)),
                new Document("$skip", offset),
                new Document("$limit", limit)));
    }

    private List<Document> run(List<Document> stages) {
        var operations = new ArrayList<AggregationOperation>();
        stages.forEach(stage -> operations.add(context -> stage));
        var options = AggregationOptions.builder().allowDiskUse(true).maxTime(Duration.ofSeconds(120)).build();
        return mongo.aggregate(Aggregation.newAggregation(operations).withOptions(options), "trips", Document.class)
                .getMappedResults();
    }
}
