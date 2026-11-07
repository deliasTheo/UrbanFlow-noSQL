package fr.urbanflow;

import org.bson.Document;

public record Zone(int id, String borough, String name) {
    public static Zone from(Document d) {
        return new Zone(((Number) d.get("_id")).intValue(), d.getString("Borough"), d.getString("Zone"));
    }
}
