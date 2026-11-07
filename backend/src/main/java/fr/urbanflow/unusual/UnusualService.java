package fr.urbanflow.unusual;

import fr.urbanflow.Counts;
import fr.urbanflow.QualityProfiles;
import fr.urbanflow.Zone;
import fr.urbanflow.activity.ActivityRepository;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.TreeSet;
import org.bson.Document;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class UnusualService {
    private final ActivityRepository reference;
    private final UnusualRepository repository;

    public UnusualService(ActivityRepository reference, UnusualRepository repository) {
        this.reference = reference;
        this.repository = repository;
    }

    public record Source(String fileId, String fileName, Counts counts) {}

    public record Day(LocalDate date, Counts counts, List<Source> sources) {}

    public record ExcludedDay(LocalDate date, String reason) {}

    public record Cell(Zone zone, Day observed, String status, String change, List<Day> references,
            Double baselineMedian, Double medianAbsoluteDeviation, Double relativeChange, Double robustScore,
            Double cityRatio, List<String> warnings) {}

    public record Rules(int minReferenceDays, int minBaseline, int minAbsoluteChange, double minRelativeChange,
            double minRobustScore) {}

    public record Response(List<Zone> area, String direction, LocalDate from, LocalDate to, LocalDate referenceFrom,
            LocalDate referenceTo, int startHour, int endHour, String timezone, String profile, List<String> excludedFlags,
            Rules rules, List<Cell> observations, List<Cell> unusual, List<Day> cityCoverage,
            List<ExcludedDay> excludedReferenceDays, List<String> sourceFiles, String holidayCalendarSource, String note) {}

    private record Key(int zone, LocalDate date) {}

    private static class Counter {
        long raw;
        long kept;
        final Map<String, long[]> files = new TreeMap<>();

        void add(String file, long raw, long kept) {
            this.raw += raw;
            this.kept += kept;
            var counts = files.computeIfAbsent(file, x -> new long[2]);
            counts[0] += raw;
            counts[1] += kept;
        }

        Day day(LocalDate date, List<Document> imports) {
            // Seuls les fichiers qui contribuent : la réponse liste déjà tous les fichiers consultés.
            var sources = imports.stream().filter(d -> files.containsKey(d.getString("_id"))).map(d -> {
                var counts = files.get(d.getString("_id"));
                return new Source(d.getString("_id"), d.getString("file_name"),
                        new Counts(counts[0], counts[1], counts[0] - counts[1]));
            }).toList();
            return new Day(date, new Counts(raw, kept, raw - kept), sources);
        }
    }

    public Response investigate(List<Integer> zoneIds, String borough, String direction, LocalDate from, LocalDate to,
            LocalDate referenceFrom, LocalDate referenceTo, int startHour, int endHour, int minReferenceDays, int minBaseline,
            int minAbsoluteChange, double minRelativeChange, double minRobustScore) {
        boolean hasZones = zoneIds != null && !zoneIds.isEmpty();
        boolean hasBorough = borough != null && !borough.isBlank();
        boolean invalidArea = hasZones == hasBorough || (hasZones && zoneIds.stream().anyMatch(Objects::isNull));
        boolean invalidDates = !from.isBefore(to) || !referenceFrom.isBefore(referenceTo) || referenceTo.isAfter(from)
                || from.getYear() != 2024 || to.minusDays(1).getYear() != 2024
                || referenceFrom.getYear() != 2024 || referenceTo.minusDays(1).getYear() != 2024;
        boolean invalidHours = startHour < 0 || endHour > 24 || startHour >= endHour;
        boolean invalidRules = minReferenceDays < 3 || minBaseline < 1 || minAbsoluteChange < 1
                || !Double.isFinite(minRelativeChange) || minRelativeChange <= 0
                || !Double.isFinite(minRobustScore) || minRobustScore <= 0;
        if (invalidArea || !List.of("pickup", "dropoff").contains(direction) || invalidDates || invalidHours || invalidRules) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Choisir zoneIds OU borough ; dates 2024, référence antérieure sans chevauchement ; "
                            + "0 <= startHour < endHour <= 24 ; minReferenceDays >= 3 et seuils positifs.");
        }

        var zones = Zone.byId(reference.zones());
        var area = new TreeSet<Integer>();
        if (hasZones) {
            for (int id : zoneIds) {
                if (!zones.containsKey(id)) {
                    throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Zone inconnue : " + id);
                }
                area.add(id);
            }
        } else {
            zones.values().stream().filter(z -> borough.trim().equalsIgnoreCase(z.borough())).forEach(z -> area.add(z.id()));
            if (area.isEmpty()) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Borough inconnu.");
            }
        }

        var imports = reference.completeImports();
        if (imports.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Aucun import complet disponible.");
        }
        imports.sort(Comparator.comparing(d -> d.getString("_id")));
        var files = imports.stream().map(d -> d.getString("_id")).toList();
        var months = imports.stream().map(d -> d.getString("file_month")).toList();

        var selected = new ArrayList<>(area);
        var data = read(repository.counts(selected, direction, from, to, referenceFrom, referenceTo, startHour, endHour, files, false));
        var city = read(repository.counts(selected, direction, from, to, referenceFrom, referenceTo, startHour, endHour, files, true));

        var excluded = new ArrayList<ExcludedDay>();
        var usable = new ArrayList<LocalDate>();
        for (var day = referenceFrom; day.isBefore(referenceTo); day = day.plusDays(1)) {
            String reason = reason(day, months, city);
            if (reason != null) {
                excluded.add(new ExcludedDay(day, reason));
            } else {
                usable.add(day);
            }
        }

        var cells = new ArrayList<Cell>();
        for (int zone : area) {
            for (var day = from; day.isBefore(to); day = day.plusDays(1)) {
                cells.add(cell(zones.get(zone), zone, day, direction, usable, data, city, months, imports,
                        minReferenceDays, minBaseline, minAbsoluteChange, minRelativeChange, minRobustScore));
            }
        }

        var anomalies = cells.stream().filter(c -> c.status().equals("UNUSUAL"))
                .sorted(Comparator.<Cell>comparingDouble(c -> Math.abs(c.relativeChange())).reversed()
                        .thenComparingInt(c -> c.zone().id())
                        .thenComparing(c -> c.observed().date()))
                .toList();

        var coverage = new TreeMap<LocalDate, Day>();
        for (var day = referenceFrom; day.isBefore(referenceTo); day = day.plusDays(1)) {
            coverage.put(day, city.getOrDefault(new Key(0, day), new Counter()).day(day, imports));
        }
        for (var day = from; day.isBefore(to); day = day.plusDays(1)) {
            coverage.put(day, city.getOrDefault(new Key(0, day), new Counter()).day(day, imports));
        }

        return new Response(area.stream().map(zones::get).toList(), direction, from, to, referenceFrom, referenceTo,
                startHour, endHour, "America/New_York", "activity", QualityProfiles.ACTIVITY,
                new Rules(minReferenceDays, minBaseline, minAbsoluteChange, minRelativeChange, minRobustScore),
                cells, anomalies, new ArrayList<>(coverage.values()), excluded, files, Calendar2024.SOURCE,
                "Comparaison descriptive, pas un test statistique. Les jours fériés fédéraux et les journées de changement d'heure sont exclus.");
    }

    // Compare une zone un jour donné aux mêmes jours de semaine de la référence.
    private static Cell cell(Zone zoneInfo, int zone, LocalDate day, String direction, List<LocalDate> usable,
            Map<Key, Counter> data, Map<Key, Counter> city, List<String> months, List<Document> imports,
            int minReferenceDays, int minBaseline, int minAbsoluteChange, double minRelativeChange, double minRobustScore) {
        var observed = data.getOrDefault(new Key(zone, day), new Counter());
        var refs = usable.stream().filter(r -> r.getDayOfWeek() == day.getDayOfWeek()).toList();
        var referenceDays = refs.stream().map(r -> data.getOrDefault(new Key(zone, r), new Counter()).day(r, imports)).toList();

        Double median = refs.isEmpty() ? null : median(referenceDays.stream().map(v -> (double) v.counts().retained()).toList());
        Double mad = median == null ? null : median(referenceDays.stream().map(v -> Math.abs(v.counts().retained() - median)).toList());
        double cityMedian = refs.isEmpty() ? 0 : median(refs.stream().map(r -> (double) city.getOrDefault(new Key(0, r), new Counter()).raw).toList());
        var global = city.getOrDefault(new Key(0, day), new Counter());
        Double cityRatio = cityMedian == 0 ? null : global.raw / cityMedian;

        var warnings = new ArrayList<String>();
        if (cityRatio != null && (cityRatio < 0.5 || cityRatio > 2)) {
            warnings.add("CITY_VOLUME_SHIFT");
        }
        if (observed.raw > 0 && (double) (observed.raw - observed.kept) / observed.raw > 0.2) {
            warnings.add("HIGH_EXCLUSION_RATE");
        }
        if (direction.equals("dropoff") && !months.contains(YearMonth.from(day).minusMonths(1).toString())) {
            warnings.add("PREVIOUS_SOURCE_MONTH_ABSENT");
        }

        Double relative = median == null || median == 0 ? null : (observed.kept - median) / median;
        Double score = mad == null || mad == 0 ? null : (observed.kept - median) / (1.4826 * mad);
        String status = reason(day, months, city);
        String change = null;
        if (status == null) {
            if (refs.size() < minReferenceDays) {
                status = "INSUFFICIENT_REFERENCE";
            } else if (median < minBaseline) {
                status = "LOW_BASELINE";
            } else {
                double delta = observed.kept - median;
                boolean unusual = Math.abs(delta) >= minAbsoluteChange && Math.abs(relative) >= minRelativeChange
                        && (mad == 0 || Math.abs(score) >= minRobustScore);
                status = unusual ? "UNUSUAL" : "USUAL";
                if (unusual) {
                    change = delta > 0 ? "HIGHER" : "LOWER";
                }
                if (mad == 0) {
                    warnings.add("ZERO_REFERENCE_MAD");
                }
            }
        }
        return new Cell(zoneInfo, observed.day(day, imports), status, change, referenceDays, median, mad, relative,
                score, cityRatio, warnings);
    }

    private static Map<Key, Counter> read(List<Document> rows) {
        var result = new HashMap<Key, Counter>();
        for (var row : rows) {
            var id = row.get("_id", Document.class);
            var key = new Key(((Number) id.get("zone")).intValue(), LocalDate.parse(id.getString("date")));
            result.computeIfAbsent(key, k -> new Counter()).add(id.getString("source"),
                    ((Number) row.get("raw")).longValue(), ((Number) row.get("retained")).longValue());
        }
        return result;
    }

    private static String reason(LocalDate day, List<String> months, Map<Key, Counter> city) {
        if (Calendar2024.transition(day)) {
            return "DST_DAY_EXCLUDED";
        }
        if (Calendar2024.holiday(day) != null) {
            return "HOLIDAY_EXCLUDED: " + Calendar2024.holiday(day);
        }
        if (!months.contains(YearMonth.from(day).toString())) {
            return "SOURCE_MONTH_MISSING";
        }
        if (city.getOrDefault(new Key(0, day), new Counter()).raw == 0) {
            return "NO_CITY_RECORDS";
        }
        return null;
    }

    private static double median(List<Double> values) {
        var sorted = values.stream().sorted().toList();
        int n = sorted.size();
        return n % 2 == 1 ? sorted.get(n / 2) : (sorted.get(n / 2 - 1) + sorted.get(n / 2)) / 2;
    }
}
