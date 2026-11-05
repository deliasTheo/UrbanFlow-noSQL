package fr.urbanflow.activity;

import java.time.LocalDate;
import java.util.*;
import org.bson.Document;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ActivityService {
    private final ActivityRepository repository;

    public ActivityService(ActivityRepository repository) { this.repository = repository; }

    public record Counts(long raw, long retained, long excluded) {}
    public record Bucket(Object value, Counts counts) {}
    public record Zone(int id, String borough, String name) {}
    public record Source(String fileId, String fileName, String fileMonth, Counts counts) {}
    public record Reason(String flag, long count) {}
    public record Activity(Zone zone, Direction direction, LocalDate from, LocalDate to,
            String timezone, String timeField, String profile, List<String> excludedFlags,
            Counts totals, List<Bucket> byHour, List<Bucket> byWeekday, List<Bucket> byDate,
            List<Reason> exclusionReasons, List<Source> sources, String coverageNote) {}

    public List<Zone> zones() { return repository.zones().stream().map(ActivityService::zone).toList(); }

    public Activity activity(int zoneId, Direction direction, LocalDate from, LocalDate to) {
        if (zoneId <= 0 || !from.isBefore(to)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Zone positive et début strictement antérieur à la fin requis.");
        }
        var zone = repository.zone(zoneId);
        if (zone == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Zone inconnue.");
        var imports = repository.completeImports();
        if (imports.isEmpty()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Aucun import complet disponible.");
        var fileIds = imports.stream().map(d -> d.getString("_id")).toList();
        var result = repository.activity(zoneId, direction, from, to, fileIds);
        var totals = rows(result, "totals");
        var sources = new ArrayList<Source>();
        var bySource = new HashMap<String, Counts>();
        rows(result, "bySource").forEach(d -> bySource.put(d.getString("_id"), counts(d)));
        // Inclut les fichiers sans contribution : zéro ne signifie pas couverture complète.
        imports.stream().sorted(Comparator.comparing(d -> d.getString("_id"))).forEach(d -> sources.add(
                new Source(d.getString("_id"), d.getString("file_name"), d.getString("file_month"),
                        bySource.getOrDefault(d.getString("_id"), new Counts(0, 0, 0)))));
        return new Activity(zone(zone), direction, from, to, "America/New_York", direction.timeField,
                "activity", ActivityRepository.EXCLUDED_FLAGS,
                totals.isEmpty() ? new Counts(0, 0, 0) : counts(totals.getFirst()),
                padded(result, "byHour", 0, 23), padded(result, "byWeekday", 1, 7),
                rows(result, "byDate").stream().map(d -> new Bucket(d.get("_id"), counts(d))).toList(),
                ActivityRepository.EXCLUDED_FLAGS.stream().map(flag -> new Reason(flag,
                        rows(result, "exclusionReasons").stream().filter(d -> flag.equals(d.getString("_id")))
                                .mapToLong(d -> ((Number) d.get("count")).longValue()).sum())).toList(),
                sources, "Imports complete uniquement ; la présence de fichiers ne garantit pas une couverture complète de l'intervalle, notamment pour les arrivées en bordure. Un zéro ne prouve pas l'absence d'activité. Les motifs d'exclusion peuvent se chevaucher.");
    }

    private static Zone zone(Document d) {
        return new Zone(((Number) d.get("_id")).intValue(), d.getString("Borough"), d.getString("Zone"));
    }
    private static Counts counts(Document d) {
        long raw = ((Number) d.get("raw")).longValue();
        long retained = ((Number) d.get("retained")).longValue();
        return new Counts(raw, retained, raw - retained);
    }
    private static List<Document> rows(Document d, String key) {
        return d == null ? List.of() : d.getList(key, Document.class, List.of());
    }
    private static List<Bucket> padded(Document d, String key, int start, int end) {
        var values = new HashMap<Integer, Counts>();
        rows(d, key).forEach(row -> values.put(((Number) row.get("_id")).intValue(), counts(row)));
        var buckets = new ArrayList<Bucket>();
        for (int i = start; i <= end; i++) buckets.add(new Bucket(i, values.getOrDefault(i, new Counts(0, 0, 0))));
        return buckets;
    }
}
