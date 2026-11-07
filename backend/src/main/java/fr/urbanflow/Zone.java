package fr.urbanflow;

import java.util.List;
import java.util.TreeMap;
import org.bson.Document;

public record Zone(int id, String borough, String name) {
    public static Zone from(Document d) {
        return new Zone(((Number) d.get("_id")).intValue(), d.getString("Borough"), d.getString("Zone"));
    }

    public static TreeMap<Integer, Zone> byId(List<Document> documents) {
        var zones = new TreeMap<Integer, Zone>();
        for (var document : documents) {
            var zone = from(document);
            zones.put(zone.id(), zone);
        }
        return zones;
    }
}
