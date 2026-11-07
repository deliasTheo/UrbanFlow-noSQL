package fr.urbanflow.changes;

import fr.urbanflow.QualityProfiles;
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
public class ChangeRepository {
    private final MongoTemplate mongo;

    public ChangeRepository(MongoTemplate mongo) {
        this.mongo = mongo;
    }

    public static List<Document> pipeline(List<Integer> zones, LocalDate from, LocalDate to, LocalDate referenceFrom,
            LocalDate referenceTo, LocalDate baselineFrom, LocalDate baselineTo, List<String> files) {
        var ranges = new ArrayList<Document>();
        for (var range : List.of(List.of(from, to), List.of(referenceFrom, referenceTo), List.of(baselineFrom, baselineTo))) {
            ranges.add(new Document("data.tpep_pickup_datetime",
                    new Document("$gte", range.get(0) + "T00:00:00").append("$lt", range.get(1) + "T00:00:00")));
        }
        var retained = new Document("$eq", List.of(new Document("$size", new Document("$setIntersection", List.of(
                new Document("$ifNull", List.of("$quality_flags", List.of())), QualityProfiles.FLOWS))), 0));
        var week = new Document("$dateToString", new Document("format", "%Y-%m-%d").append("date", new Document("$dateTrunc",
                new Document("date", new Document("$dateFromString", new Document("dateString", "$data.tpep_pickup_datetime")))
                        .append("unit", "week").append("startOfWeek", "monday"))));
        return List.of(
                new Document("$match", new Document("data.PULocationID", new Document("$in", zones))
                        .append("source.file_id", new Document("$in", files))
                        .append("$or", ranges)),
                new Document("$project", new Document("origin", "$data.PULocationID")
                        .append("destination", "$data.DOLocationID")
                        .append("source", "$source.file_id")
                        .append("week", week)
                        .append("retained", retained)),
                new Document("$group", new Document("_id", new Document("origin", "$origin")
                        .append("destination", "$destination").append("week", "$week").append("source", "$source"))
                        .append("raw", new Document("$sum", 1))
                        .append("retained", new Document("$sum", new Document("$cond", List.of("$retained", 1, 0))))));
    }

    public List<Document> counts(List<Integer> zones, LocalDate from, LocalDate to, LocalDate referenceFrom,
            LocalDate referenceTo, LocalDate baselineFrom, LocalDate baselineTo, List<String> files) {
        var stages = pipeline(zones, from, to, referenceFrom, referenceTo, baselineFrom, baselineTo, files);
        var operations = stages.stream().<AggregationOperation>map(stage -> context -> stage).toList();
        var options = AggregationOptions.builder().allowDiskUse(true).maxTime(Duration.ofSeconds(300)).build();
        return mongo.aggregate(Aggregation.newAggregation(operations).withOptions(options), "trips", Document.class)
                .getMappedResults();
    }
}
