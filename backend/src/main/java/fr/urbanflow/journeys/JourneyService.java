package fr.urbanflow.journeys;

import fr.urbanflow.QualityProfiles;
import fr.urbanflow.Zone;
import fr.urbanflow.activity.ActivityRepository;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.TreeSet;
import org.bson.Document;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class JourneyService {
    private static final List<String> ACTIVITY = QualityProfiles.ACTIVITY;
    private static final List<String> JOURNEY = QualityProfiles.JOURNEY;
    // Les quantiles exacts demandent de garder les valeurs en mémoire.
    private static final long MAX_ROWS = 200000;

    private final ActivityRepository reference;
    private final JourneyRepository repository;

    public JourneyService(ActivityRepository reference, JourneyRepository repository) {
        this.reference = reference;
        this.repository = repository;
    }

    public record Metric(long count, long missing, Double min, Double q25, Double median, Double q75, Double p90,
            Double max, Double mean, Double populationStdDev, Double iqr, long iqrOutliers) {}

    public record Statistics(long records, Metric durationSeconds, Metric distanceMiles) {}

    public record Source(String fileId, String fileName, long raw, long retained, long lessReliable, long activityExcluded) {}

    public record Stratum(String key, Statistics stats) {}

    public record Period(LocalDate from, LocalDate to, long raw, long retained, long lessReliable, long activityExcluded,
            long dstSpanningRetained, Statistics usable, Statistics unreliable, List<Stratum> strata,
            Map<String, Long> exclusionReasons, List<Source> sources, List<String> missingSourceMonths) {}

    public record Comparison(String status, Double durationMedianDifferenceSeconds, Double distanceMedianDifferenceMiles,
            int commonStrata, long referenceCommonRecords, long currentCommonRecords, Double referenceCommonFraction,
            Double currentCommonFraction, Double standardizedReferenceDurationSeconds,
            Double standardizedCurrentDurationSeconds, Double standardizedDurationDifferenceSeconds, String method) {}

    public record Response(Zone origin, Zone destination, String timezone, String timeField, String profile,
            List<String> excludedFlags, int minTrips, Period reference, Period current, Comparison comparison, String note) {}

    private static class Values {
        long records;
        final List<Double> durations = new ArrayList<>();
        final List<Double> distances = new ArrayList<>();

        void add(Document d) {
            records++;
            addNumber(d.get("duration"), durations);
            addNumber(d.get("distance"), distances);
        }

        Statistics stats() {
            return new Statistics(records, metric(durations, records), metric(distances, records));
        }
    }

    private static class Accumulator {
        long raw;
        long kept;
        long less;
        long activityExcluded;
        long dst;
        final Values usable = new Values();
        final Values unreliable = new Values();
        final Map<String, Values> strata = new TreeMap<>();
        // Pour chaque fichier : brutes, retenues, moins fiables, exclues par activity.
        final Map<String, long[]> sources = new TreeMap<>();
        final Map<String, Long> reasons = new TreeMap<>();

        void add(Document d) {
            raw++;
            var source = sources.computeIfAbsent(d.getString("source"), k -> new long[4]);
            source[0]++;

            var flags = d.getList("flags", String.class, List.of());
            for (String flag : JOURNEY) {
                if (flags.contains(flag)) {
                    reasons.merge(flag, 1L, Long::sum);
                }
            }
            if (flags.stream().anyMatch(ACTIVITY::contains)) {
                activityExcluded++;
                source[3]++;
                return;
            }
            if (flags.stream().anyMatch(JOURNEY::contains)) {
                less++;
                source[2]++;
                unreliable.add(d);
                return;
            }

            kept++;
            source[1]++;
            usable.add(d);
            if (flags.contains("DST_SPANNING")) {
                dst++;
            }
            strata.computeIfAbsent(stratumKey(d), k -> new Values()).add(d);
        }

        Period period(LocalDate from, LocalDate to, List<Document> imports) {
            var known = imports.stream().map(d -> d.getString("file_month")).toList();
            var missing = new ArrayList<String>();
            for (var month = YearMonth.from(from); !month.isAfter(YearMonth.from(to.minusDays(1))); month = month.plusMonths(1)) {
                if (!known.contains(month.toString())) {
                    missing.add(month.toString());
                }
            }
            var strataStats = strata.entrySet().stream().map(e -> new Stratum(e.getKey(), e.getValue().stats())).toList();
            var fileCounts = imports.stream().map(d -> {
                var c = sources.getOrDefault(d.getString("_id"), new long[4]);
                return new Source(d.getString("_id"), d.getString("file_name"), c[0], c[1], c[2], c[3]);
            }).toList();
            return new Period(from, to, raw, kept, less, activityExcluded, dst, usable.stats(), unreliable.stats(),
                    strataStats, new TreeMap<>(reasons), fileCounts, missing);
        }
    }

    // Jour ouvré ou week-end, créneau de six heures et classe de distance.
    private static String stratumKey(Document d) {
        int hour = ((Number) d.get("hour")).intValue();
        int weekday = ((Number) d.get("weekday")).intValue();
        double distance = d.get("distance") instanceof Number n ? n.doubleValue() : Double.NaN;
        String miles;
        if (!Double.isFinite(distance)) {
            miles = "missing";
        } else if (distance < 2) {
            miles = "0-2";
        } else if (distance < 5) {
            miles = "2-5";
        } else if (distance < 10) {
            miles = "5-10";
        } else {
            miles = "10+";
        }
        return (weekday >= 6 ? "weekend" : "weekday") + "_h" + (hour / 6 * 6) + "_mi" + miles;
    }

    public Response compare(int originId, int destinationId, LocalDate from, LocalDate to,
            LocalDate referenceFrom, LocalDate referenceTo, int minTrips) {
        if (!from.isBefore(to) || !referenceFrom.isBefore(referenceTo) || referenceTo.isAfter(from) || minTrips < 2) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Intervalles non vides, référence antérieure sans chevauchement et minTrips >= 2 requis.");
        }
        var origin = reference.zone(originId);
        var destination = reference.zone(destinationId);
        if (origin == null || destination == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Zone inconnue.");
        }
        var imports = reference.completeImports();
        if (imports.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Aucun import complet disponible.");
        }
        imports.sort(Comparator.comparing(d -> d.getString("_id")));

        var before = new Accumulator();
        var after = new Accumulator();
        long count = 0;
        var files = imports.stream().map(d -> d.getString("_id")).toList();
        try (var rows = repository.rows(originId, destinationId, from, to, referenceFrom, referenceTo, files)) {
            var iterator = rows.iterator();
            while (iterator.hasNext()) {
                if (++count > MAX_ROWS) {
                    throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                            "Plus de 200 000 lignes candidates : réduire les intervalles pour les quantiles exacts. Aucun résultat partiel fourni.");
                }
                var d = iterator.next();
                (d.getString("period").equals("reference") ? before : after).add(d);
            }
        }
        var referencePeriod = before.period(referenceFrom, referenceTo, imports);
        var currentPeriod = after.period(from, to, imports);

        // Strates assez fournies dans les deux périodes.
        var keys = new TreeSet<>(before.strata.keySet());
        keys.retainAll(after.strata.keySet());
        keys.removeIf(k -> before.strata.get(k).durations.size() < minTrips || after.strata.get(k).durations.size() < minTrips);
        long referenceCommon = keys.stream().mapToLong(k -> before.strata.get(k).records).sum();
        long currentCommon = keys.stream().mapToLong(k -> after.strata.get(k).records).sum();

        // Mêmes poids des deux côtés : ceux de la période de référence.
        double standardizedBefore = 0;
        double standardizedAfter = 0;
        for (String key : keys) {
            double weight = (double) before.strata.get(key).records / referenceCommon;
            standardizedBefore += weight * before.strata.get(key).stats().durationSeconds().mean();
            standardizedAfter += weight * after.strata.get(key).stats().durationSeconds().mean();
        }

        boolean enough = before.usable.durations.size() >= minTrips && after.usable.durations.size() >= minTrips;
        boolean enoughDistance = before.usable.distances.size() >= minTrips && after.usable.distances.size() >= minTrips;
        String status;
        if (!referencePeriod.missingSourceMonths().isEmpty() || !currentPeriod.missingSourceMonths().isEmpty()) {
            status = "SOURCE_MONTH_MISSING";
        } else if (!enough) {
            status = "INSUFFICIENT_SAMPLE";
        } else if (keys.isEmpty()) {
            status = "NO_COMMON_STRATA";
        } else {
            status = "COMPARABLE";
        }
        boolean comparable = status.equals("COMPARABLE");

        var comparison = new Comparison(status,
                enough ? currentPeriod.usable().durationSeconds().median() - referencePeriod.usable().durationSeconds().median() : null,
                enoughDistance ? currentPeriod.usable().distanceMiles().median() - referencePeriod.usable().distanceMiles().median() : null,
                keys.size(), referenceCommon, currentCommon,
                before.kept == 0 ? null : (double) referenceCommon / before.kept,
                after.kept == 0 ? null : (double) currentCommon / after.kept,
                comparable ? standardizedBefore : null,
                comparable ? standardizedAfter : null,
                comparable ? standardizedAfter - standardizedBefore : null,
                "Moyennes de durée pondérées par les effectifs de la référence, sur les strates communes.");
        return new Response(Zone.from(origin), Zone.from(destination), "America/New_York", "data.tpep_pickup_datetime",
                "journey", JOURNEY, minTrips, referencePeriod, currentPeriod, comparison,
                "Quantiles exacts, durées en secondes, distances en miles. Les jours fériés ne sont pas neutralisés.");
    }

    private static void addNumber(Object value, List<Double> target) {
        if (value instanceof Number n && Double.isFinite(n.doubleValue())) {
            target.add(n.doubleValue());
        }
    }

    private static double quantile(List<Double> sorted, double p) {
        double position = (sorted.size() - 1) * p;
        int below = (int) position;
        int above = (int) Math.ceil(position);
        return sorted.get(below) + (sorted.get(above) - sorted.get(below)) * (position - below);
    }

    private static Metric metric(List<Double> values, long total) {
        // Trier d'abord rend la somme indépendante de l'ordre de lecture de MongoDB.
        var sorted = values.stream().sorted().toList();
        int n = sorted.size();
        if (n == 0) {
            return new Metric(0, total, null, null, null, null, null, null, null, null, null, 0);
        }
        double q25 = quantile(sorted, 0.25);
        double q75 = quantile(sorted, 0.75);
        double iqr = q75 - q25;
        double mean = sorted.stream().mapToDouble(Double::doubleValue).average().orElseThrow();
        double variance = sorted.stream().mapToDouble(v -> (v - mean) * (v - mean)).average().orElseThrow();
        long outliers = sorted.stream().filter(v -> v < q25 - 1.5 * iqr || v > q75 + 1.5 * iqr).count();
        return new Metric(n, total - n, sorted.getFirst(), q25, quantile(sorted, 0.5), q75, quantile(sorted, 0.9),
                sorted.getLast(), mean, Math.sqrt(variance), iqr, outliers);
    }
}
