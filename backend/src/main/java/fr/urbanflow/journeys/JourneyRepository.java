package fr.urbanflow.journeys;

import java.time.*;
import java.util.List;
import java.util.stream.Stream;
import org.bson.Document;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.aggregation.*;
import org.springframework.stereotype.Repository;

@Repository
public class JourneyRepository {
    private final MongoTemplate mongo;
    public JourneyRepository(MongoTemplate mongo) { this.mongo=mongo; }
    public static List<Document> pipeline(int origin,int destination,LocalDate from,LocalDate to,
            LocalDate referenceFrom,LocalDate referenceTo,List<String> files) {
        var match=new Document("data.PULocationID",origin).append("data.DOLocationID",destination)
            .append("source.file_id",new Document("$in",files)).append("$or",List.of(
                new Document("data.tpep_pickup_datetime",new Document("$gte",from+"T00:00:00").append("$lt",to+"T00:00:00")),
                new Document("data.tpep_pickup_datetime",new Document("$gte",referenceFrom+"T00:00:00").append("$lt",referenceTo+"T00:00:00"))));
        var date=new Document("$dateFromString",new Document("dateString","$data.tpep_pickup_datetime"));
        return List.of(new Document("$match",match),new Document("$project",new Document("_id",0)
            .append("period",new Document("$cond",List.of(new Document("$gte",List.of("$data.tpep_pickup_datetime",from+"T00:00:00")),"current","reference")))
            .append("source","$source.file_id").append("flags",new Document("$ifNull",List.of("$quality_flags",List.of())))
            .append("duration","$duration_s").append("distance","$data.trip_distance")
            .append("hour",new Document("$hour",date)).append("weekday",new Document("$isoDayOfWeek",date))));
    }
    public Stream<Document> rows(int origin,int destination,LocalDate from,LocalDate to,
            LocalDate referenceFrom,LocalDate referenceTo,List<String> files) {
        var ops=pipeline(origin,destination,from,to,referenceFrom,referenceTo,files).stream()
            .<AggregationOperation>map(d -> context -> d).toList();
        return mongo.aggregateStream(Aggregation.newAggregation(ops).withOptions(AggregationOptions.builder()
            .cursorBatchSize(2000).maxTime(Duration.ofSeconds(120)).build()),"trips",Document.class);
    }
}
