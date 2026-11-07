package fr.urbanflow.trips;

import fr.urbanflow.Counts;
import fr.urbanflow.QualityProfiles;
import fr.urbanflow.activity.ActivityRepository;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import org.bson.Document;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

// Remonte d'un résultat aux lignes qui le justifient : combien, et dans quel fichier.
@Service
public class TripService {
    private static final Map<String, List<String>> PROFILES = Map.of(
            "activity", QualityProfiles.ACTIVITY,
            "flows", QualityProfiles.FLOWS,
            "journey", QualityProfiles.JOURNEY);
    private static final int MAX_LIMIT = 1000;

    private final ActivityRepository reference;
    private final TripRepository repository;

    public TripService(ActivityRepository reference, TripRepository repository) {
        this.reference = reference;
        this.repository = repository;
    }

    public record Source(String fileId, String fileName, Counts counts) {}

    public record Trip(String id, String fileId, String fileName, long rowNumber, String pickup, String dropoff,
            int pickupZoneId, int dropoffZoneId, Double distanceMiles, Double totalAmount, Double durationSeconds,
            List<String> flags, boolean retained) {}

    public record Response(Integer pickupZoneId, Integer dropoffZoneId, String timeField, LocalDate from, LocalDate to,
            int startHour, int endHour, String profile, List<String> excludedFlags, String status, Counts totals,
            List<Source> sources, int offset, int limit, List<Trip> trips) {}

    public Response trips(Integer pickupZoneId, Integer dropoffZoneId, String time, LocalDate from, LocalDate to,
            int startHour, int endHour, String profile, String status, int offset, int limit) {
        boolean invalidHours = startHour < 0 || endHour > 24 || startHour >= endHour;
        if ((pickupZoneId == null && dropoffZoneId == null) || !from.isBefore(to) || invalidHours
                || !List.of("pickup", "dropoff").contains(time) || !PROFILES.containsKey(profile)
                || !List.of("all", "retained", "excluded").contains(status)
                || offset < 0 || limit < 1 || limit > MAX_LIMIT) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Au moins une zone, début < fin, 0 <= startHour < endHour <= 24, time pickup ou dropoff, "
                            + "profile activity, flows ou journey, status all, retained ou excluded, limit 1.." + MAX_LIMIT + ".");
        }
        for (Integer id : new Integer[] {pickupZoneId, dropoffZoneId}) {
            if (id != null && reference.zone(id) == null) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Zone inconnue : " + id);
            }
        }
        var imports = reference.completeImports();
        if (imports.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Aucun import complet disponible.");
        }
        imports.sort(Comparator.comparing(d -> d.getString("_id")));
        var files = imports.stream().map(d -> d.getString("_id")).toList();

        String timeField = "data.tpep_" + time + "_datetime";
        var excludedFlags = PROFILES.get(profile);
        var selection = new TripRepository.Selection(pickupZoneId, dropoffZoneId, timeField, from, to, startHour, endHour, files);

        var counts = repository.countsBySource(selection, excludedFlags);
        var sources = new ArrayList<Source>();
        long raw = 0;
        long retained = 0;
        for (var file : imports) {
            String fileId = file.getString("_id");
            for (var row : counts) {
                if (fileId.equals(row.getString("_id"))) {
                    long fileRaw = ((Number) row.get("raw")).longValue();
                    long fileRetained = ((Number) row.get("retained")).longValue();
                    sources.add(new Source(fileId, file.getString("file_name"), new Counts(fileRaw, fileRetained, fileRaw - fileRetained)));
                    raw += fileRaw;
                    retained += fileRetained;
                }
            }
        }

        var rows = repository.trips(selection, qualityFilter(status, excludedFlags), offset, limit);
        var trips = rows.stream().map(row -> trip(row, imports, excludedFlags)).toList();
        return new Response(pickupZoneId, dropoffZoneId, timeField, from, to, startHour, endHour, profile, excludedFlags,
                status, new Counts(raw, retained, raw - retained), sources, offset, limit, trips);
    }

    private static Document qualityFilter(String status, List<String> excludedFlags) {
        return switch (status) {
            case "retained" -> new Document("quality_flags", new Document("$nin", excludedFlags));
            case "excluded" -> new Document("quality_flags", new Document("$in", excludedFlags));
            default -> new Document();
        };
    }

    private static Trip trip(Document row, List<Document> imports, List<String> excludedFlags) {
        var source = row.get("source", Document.class);
        var data = row.get("data", Document.class);
        String fileId = source.getString("file_id");
        String fileName = imports.stream().filter(d -> fileId.equals(d.getString("_id")))
                .map(d -> d.getString("file_name")).findFirst().orElse(null);
        var flags = row.getList("quality_flags", String.class, List.of());
        return new Trip(row.getString("_id"), fileId, fileName, ((Number) source.get("row_number")).longValue(),
                data.getString("tpep_pickup_datetime"), data.getString("tpep_dropoff_datetime"),
                ((Number) data.get("PULocationID")).intValue(), ((Number) data.get("DOLocationID")).intValue(),
                number(data.get("trip_distance")), number(data.get("total_amount")), number(row.get("duration_s")),
                flags, flags.stream().noneMatch(excludedFlags::contains));
    }

    private static Double number(Object value) {
        return value instanceof Number n ? n.doubleValue() : null;
    }
}
