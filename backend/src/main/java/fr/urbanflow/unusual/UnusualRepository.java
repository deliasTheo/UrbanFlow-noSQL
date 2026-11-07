package fr.urbanflow.unusual;

import fr.urbanflow.QualityProfiles;
import java.time.*;
import java.util.ArrayList;
import java.util.List;
import org.bson.Document;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.aggregation.*;
import org.springframework.stereotype.Repository;

@Repository
public class UnusualRepository {
    private final MongoTemplate mongo;
    public UnusualRepository(MongoTemplate mongo) { this.mongo=mongo; }
    public static List<Document> pipeline(List<Integer> zones, String direction, LocalDate from, LocalDate to,
            LocalDate referenceFrom, LocalDate referenceTo, int startHour, int endHour, List<String> files, boolean city) {
        String time="data.tpep_"+direction+"_datetime", zone="data."+(direction.equals("pickup")?"PULocationID":"DOLocationID");
        var match=new Document("source.file_id",new Document("$in",files)).append("$or",List.of(
            new Document(time,new Document("$gte",from+"T00:00:00").append("$lt",to+"T00:00:00")),
            new Document(time,new Document("$gte",referenceFrom+"T00:00:00").append("$lt",referenceTo+"T00:00:00"))));
        if (!city) match.append(zone,new Document("$in",zones));
        var retained=new Document("$eq",List.of(new Document("$size",new Document("$setIntersection",List.of(
            new Document("$ifNull",List.of("$quality_flags",List.of())),QualityProfiles.ACTIVITY))),0));
        var project=new Document("zone",city?new Document("$literal",0):"$"+zone)
            .append("date",new Document("$substrBytes",List.of("$"+time,0,10)))
            .append("source","$source.file_id").append("retained",retained);
        var stages=new ArrayList<Document>();
        stages.add(new Document("$match",match));
        // Le pipeline ville lit des millions de documents. L'heure se lit directement dans la
        // chaîne AAAA-MM-JJTHH:MM:SS, et n'est pas calculée du tout quand on veut toute la journée.
        if (startHour==0&&endHour==24) {
            stages.add(new Document("$project",project));
        } else {
            project.append("hour",new Document("$toInt",new Document("$substrBytes",List.of("$"+time,11,2))));
            stages.add(new Document("$project",project));
            stages.add(new Document("$match",new Document("hour",new Document("$gte",startHour).append("$lt",endHour))));
        }
        stages.add(new Document("$group",new Document("_id",new Document("zone","$zone").append("date","$date").append("source","$source"))
            .append("raw",new Document("$sum",1)).append("retained",new Document("$sum",new Document("$cond",List.of("$retained",1,0))))));
        return stages;
    }
    public List<Document> counts(List<Integer> zones,String direction,LocalDate from,LocalDate to,LocalDate referenceFrom,
            LocalDate referenceTo,int startHour,int endHour,List<String> files,boolean city) {
        var ops=pipeline(zones,direction,from,to,referenceFrom,referenceTo,startHour,endHour,files,city).stream()
            .<AggregationOperation>map(d -> context -> d).toList();
        return mongo.aggregate(Aggregation.newAggregation(ops).withOptions(AggregationOptions.builder()
            .allowDiskUse(true).maxTime(Duration.ofSeconds(300)).build()),"trips",Document.class).getMappedResults();
    }
}
