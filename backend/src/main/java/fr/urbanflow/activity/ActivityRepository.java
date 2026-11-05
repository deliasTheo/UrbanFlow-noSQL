package fr.urbanflow.activity;

import java.time.Duration;
import java.time.LocalDate;
import java.util.List;
import org.bson.Document;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.aggregation.Aggregation;
import org.springframework.data.mongodb.core.aggregation.AggregationOperation;
import org.springframework.data.mongodb.core.aggregation.AggregationOptions;
import org.springframework.data.mongodb.core.query.Criteria;
import org.springframework.data.mongodb.core.query.Query;
import org.springframework.stereotype.Repository;

@Repository
public class ActivityRepository {
    // Même profil activity que dans urbanflow/quality.py. Les motifs se chevauchent.
    static final List<String> EXCLUDED_FLAGS = List.of("NEGATIVE_AMOUNT", "EXACT_DUPLICATE");
    private final MongoTemplate mongo;

    public ActivityRepository(MongoTemplate mongo) { this.mongo = mongo; }

    public Document zone(int id) { return mongo.findById(id, Document.class, "zones"); }

    public List<Document> zones() {
        return mongo.find(new Query().with(org.springframework.data.domain.Sort.by("_id")),
                Document.class, "zones");
    }

    public List<Document> completeImports() {
        return mongo.find(Query.query(Criteria.where("status").is("complete")), Document.class, "imports");
    }

    public Document activity(int zoneId, Direction direction, LocalDate from, LocalDate to, List<String> fileIds) {
        var match = new Document(direction.zoneField, zoneId)
                .append(direction.timeField, new Document("$gte", from + "T00:00:00")
                        .append("$lt", to + "T00:00:00"))
                .append("source.file_id", new Document("$in", fileIds));
        // Les dates stockées sont des chaînes locales ISO. On les interprète sans
        // décalage pour extraire l'heure et le jour locaux, sans calcul de durée.
        var date = new Document("$dateFromString", new Document("dateString", "$" + direction.timeField));
        var retained = new Document("$eq", List.of(new Document("$size",
                new Document("$setIntersection", List.of(
                        new Document("$ifNull", List.of("$quality_flags", List.of())), EXCLUDED_FLAGS))), 0));
        var project = new Document("retained", retained)
                .append("hour", new Document("$hour", date))
                .append("weekday", new Document("$isoDayOfWeek", date))
                .append("date", new Document("$substrBytes", List.of("$" + direction.timeField, 0, 10)))
                .append("fileId", "$source.file_id").append("quality_flags", 1);
        var facets = new Document("totals", counts(null))
                .append("byHour", counts("$hour"))
                .append("byWeekday", counts("$weekday"))
                .append("byDate", counts("$date"))
                .append("bySource", counts("$fileId"))
                .append("exclusionReasons", List.of(
                        new Document("$unwind", "$quality_flags"),
                        new Document("$match", new Document("quality_flags", new Document("$in", EXCLUDED_FLAGS))),
                        new Document("$group", new Document("_id", "$quality_flags").append("count", new Document("$sum", 1))),
                        new Document("$sort", new Document("_id", 1))));
        List<AggregationOperation> operations = List.of(
                context -> new Document("$match", match),
                context -> new Document("$project", project),
                context -> new Document("$facet", facets));
        var aggregation = Aggregation.newAggregation(operations).withOptions(
                AggregationOptions.builder().maxTime(Duration.ofSeconds(120)).build());
        return mongo.aggregate(aggregation, "trips", Document.class).getUniqueMappedResult();
    }

    private static List<Document> counts(String key) {
        return List.of(new Document("$group", new Document("_id", key)
                        .append("raw", new Document("$sum", 1))
                        .append("retained", new Document("$sum", new Document("$cond", List.of("$retained", 1, 0))))),
                new Document("$sort", new Document("_id", 1)));
    }
}
