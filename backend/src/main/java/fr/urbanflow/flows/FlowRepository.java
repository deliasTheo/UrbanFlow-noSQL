package fr.urbanflow.flows;

import java.time.Duration;
import java.time.LocalDate;
import java.util.List;
import org.bson.Document;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.aggregation.*;
import org.springframework.stereotype.Repository;

@Repository
public class FlowRepository {
    public static final List<String> EXCLUDED = List.of("NEGATIVE_AMOUNT", "EXACT_DUPLICATE", "UNKNOWN_ZONE");
    private final MongoTemplate mongo;
    public FlowRepository(MongoTemplate mongo) { this.mongo = mongo; }

    // Public pour réutiliser exactement le pipeline dans le benchmark explain.
    public static List<Document> pipeline(List<Integer> zones, LocalDate from, LocalDate to, List<String> files) {
        var match = new Document("source.file_id", new Document("$in", files))
                .append("data.tpep_pickup_datetime", new Document("$gte", from + "T00:00:00").append("$lt", to + "T00:00:00"))
                .append("$or", List.of(new Document("data.PULocationID", new Document("$in", zones)),
                        new Document("data.DOLocationID", new Document("$in", zones))));
        var retained = new Document("$eq", List.of(new Document("$size", new Document("$setIntersection",
                List.of(new Document("$ifNull", List.of("$quality_flags", List.of())), EXCLUDED))), 0));
        var week = new Document("$dateToString", new Document("format", "%Y-%m-%d").append("date",
                new Document("$dateTrunc", new Document("date", new Document("$dateFromString",
                        new Document("dateString", "$data.tpep_pickup_datetime")))
                        .append("unit", "week").append("startOfWeek", "monday"))));
        return List.of(new Document("$match", match), new Document("$project",
                new Document("origin", "$data.PULocationID").append("destination", "$data.DOLocationID")
                        .append("source", "$source.file_id").append("week", week).append("retained", retained)),
                new Document("$group", new Document("_id", new Document("origin", "$origin")
                        .append("destination", "$destination").append("week", "$week").append("source", "$source"))
                        .append("raw", new Document("$sum", 1))
                        .append("retained", new Document("$sum", new Document("$cond", List.of("$retained", 1, 0))))));
    }

    public List<Document> flows(List<Integer> zones, LocalDate from, LocalDate to, List<String> files) {
        var ops = pipeline(zones, from, to, files).stream()
                .<AggregationOperation>map(stage -> context -> stage).toList();
        return mongo.aggregate(Aggregation.newAggregation(ops).withOptions(AggregationOptions.builder()
                .allowDiskUse(true).maxTime(Duration.ofSeconds(120)).build()), "trips", Document.class).getMappedResults();
    }
}
