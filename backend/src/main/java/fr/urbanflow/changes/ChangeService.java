package fr.urbanflow.changes;

import fr.urbanflow.Counts;
import fr.urbanflow.QualityProfiles;
import fr.urbanflow.Zone;
import fr.urbanflow.activity.ActivityRepository;
import fr.urbanflow.unusual.Calendar2024;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.function.UnaryOperator;
import org.bson.Document;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ChangeService {
    private final ActivityRepository reference;
    private final ChangeRepository repository;

    public ChangeService(ActivityRepository reference, ChangeRepository repository) {
        this.reference = reference;
        this.repository = repository;
    }

    public record Source(String fileId, String fileName, Counts counts) {}

    public record Week(LocalDate start, Counts counts, List<Source> sources, boolean usable, List<String> warnings) {}

    public record Period(LocalDate from, LocalDate to, Counts counts, List<Source> sources, List<Week> weeks) {}

    public record PairWeek(LocalDate start, Counts counts, long denominator, Double share, List<Source> sources) {}

    public record Change(Zone origin, Zone destination, Counts referenceCounts, Counts currentCounts,
            List<Source> referenceSources, List<Source> currentSources, Double referenceShare, Double currentShare,
            Double shareChange, Double percentagePointChange, Double relativeShareChange,
            Double expectedCurrentAtReferenceShare, Double volumeOnlyCountChange, Double residualCountChange,
            String status, Double typicalWeeklyChange, Double p90WeeklyChange, Double variationRatio,
            List<PairWeek> baselineWeeks, List<Double> adjacentWeeklyChanges) {}

    public record Rules(int minTrips, int minBaselineTrips, int minTotalTrips, int minBaselineWeeks,
            double minShareChange, double minVariationRatio, int limit) {}

    public record Response(List<Zone> area, String denominator, String timeField, String profile,
            List<String> excludedFlags, Rules rules, Period reference, Period current, Period baseline, String status,
            Double totalVolumeChange, long pairsConsidered, long qualifiedPairs, List<Change> increases,
            List<Change> decreases, List<Change> otherLargestChanges, List<String> sourceFiles, String ranking,
            String note) {}

    private record Pair(int origin, int destination) {}

    private static class Counter {
        long raw;
        long kept;
        final Map<String, long[]> files = new TreeMap<>();

        void add(String file, long raw, long kept) {
            this.raw += raw;
            this.kept += kept;
            var counts = files.computeIfAbsent(file, k -> new long[2]);
            counts[0] += raw;
            counts[1] += kept;
        }

        void add(Counter other) {
            other.files.forEach((file, counts) -> add(file, counts[0], counts[1]));
        }

        Counts counts() {
            return new Counts(raw, kept, raw - kept);
        }

        List<Source> sources(List<Document> imports) {
            return imports.stream().map(d -> {
                var counts = files.getOrDefault(d.getString("_id"), new long[2]);
                return new Source(d.getString("_id"), d.getString("file_name"),
                        new Counts(counts[0], counts[1], counts[0] - counts[1]));
            }).toList();
        }
    }

    public Response compare(List<Integer> zoneIds, String borough, LocalDate from, LocalDate to,
            LocalDate referenceFrom, LocalDate referenceTo, LocalDate baselineFrom, LocalDate baselineTo,
            int minTrips, int minBaselineTrips, int minTotalTrips, int minBaselineWeeks,
            double minShareChange, double minVariationRatio, int limit) {
        boolean hasZones = zoneIds != null && !zoneIds.isEmpty();
        boolean hasBorough = borough != null && !borough.isBlank();
        boolean invalidDates = !fullWeeks(from, to) || !fullWeeks(referenceFrom, referenceTo)
                || !fullWeeks(baselineFrom, baselineTo) || referenceTo.isAfter(from) || baselineTo.isAfter(from)
                || ChronoUnit.DAYS.between(from, to) != ChronoUnit.DAYS.between(referenceFrom, referenceTo)
                || List.of(from, referenceFrom, baselineFrom).stream().anyMatch(d -> d.getYear() != 2024)
                || List.of(to, referenceTo, baselineTo).stream().anyMatch(d -> d.minusDays(1).getYear() != 2024);
        boolean invalidRules = minTrips < 1 || minBaselineTrips < 1 || minTotalTrips < 1 || minBaselineWeeks < 3
                || limit < 1 || limit > 100
                || !Double.isFinite(minShareChange) || minShareChange <= 0 || minShareChange > 1
                || !Double.isFinite(minVariationRatio) || minVariationRatio < 1;
        boolean invalidArea = (hasZones && hasBorough) || (hasZones && zoneIds.stream().anyMatch(Objects::isNull));
        if (invalidArea || invalidDates || invalidRules) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Dates 2024 lundi à lundi ; périodes comparées de même durée, référence et baseline avant la période courante ; "
                            + "seuils positifs, minBaselineWeeks >= 3, ratio >= 1, limit 1..100. zoneIds OU borough ou aucun pour toute la ville.");
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
        } else if (hasBorough) {
            zones.values().stream().filter(z -> borough.trim().equalsIgnoreCase(z.borough())).forEach(z -> area.add(z.id()));
            if (area.isEmpty()) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Borough inconnu.");
            }
        } else {
            area.addAll(zones.keySet());
        }

        var imports = reference.completeImports();
        if (imports.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Aucun import complet disponible.");
        }
        imports.sort(Comparator.comparing(d -> d.getString("_id")));
        var files = imports.stream().map(d -> d.getString("_id")).toList();
        var months = imports.stream().map(d -> d.getString("file_month")).toList();

        // Comptes de chaque flux par semaine, et total de l'aire par semaine.
        var pairs = new HashMap<Pair, Map<LocalDate, Counter>>();
        var totals = new TreeMap<LocalDate, Counter>();
        var rows = repository.counts(new ArrayList<>(area), from, to, referenceFrom, referenceTo, baselineFrom, baselineTo, files);
        for (var row : rows) {
            var id = row.get("_id", Document.class);
            var key = new Pair(((Number) id.get("origin")).intValue(), ((Number) id.get("destination")).intValue());
            var week = LocalDate.parse(id.getString("week"));
            long raw = ((Number) row.get("raw")).longValue();
            long kept = ((Number) row.get("retained")).longValue();
            String file = id.getString("source");
            pairs.computeIfAbsent(key, k -> new TreeMap<>()).computeIfAbsent(week, k -> new Counter()).add(file, raw, kept);
            totals.computeIfAbsent(week, k -> new Counter()).add(file, raw, kept);
        }

        var referencePeriod = period(referenceFrom, referenceTo, totals, months, minTotalTrips, imports);
        var currentPeriod = period(from, to, totals, months, minTotalTrips, imports);
        var history = period(baselineFrom, baselineTo, totals, months, minTotalTrips, imports);
        String status = globalStatus(referencePeriod, currentPeriod, history, minBaselineWeeks);

        var changes = new ArrayList<Change>();
        long referenceTotal = referencePeriod.counts().retained();
        long currentTotal = currentPeriod.counts().retained();
        for (var entry : pairs.entrySet()) {
            var key = entry.getKey();
            var values = entry.getValue();
            var inReference = sum(values, referenceFrom, referenceTo);
            var inCurrent = sum(values, from, to);
            if (inReference.kept == 0 && inCurrent.kept == 0) {
                continue;
            }

            Double referenceShare = referenceTotal == 0 ? null : (double) inReference.kept / referenceTotal;
            Double currentShare = currentTotal == 0 ? null : (double) inCurrent.kept / currentTotal;
            Double delta = referenceShare == null || currentShare == null ? null : currentShare - referenceShare;

            // Part du flux chaque semaine de l'historique, puis écarts entre semaines voisines.
            var shares = new TreeMap<LocalDate, Double>();
            long baselineCount = 0;
            for (var week : history.weeks()) {
                if (week.usable()) {
                    var counter = values.getOrDefault(week.start(), new Counter());
                    shares.put(week.start(), (double) counter.kept / week.counts().retained());
                    baselineCount += counter.kept;
                }
            }
            var adjacent = new ArrayList<Double>();
            for (var week : shares.keySet()) {
                if (shares.containsKey(week.minusWeeks(1))) {
                    adjacent.add(shares.get(week) - shares.get(week.minusWeeks(1)));
                }
            }
            var absolute = adjacent.stream().map(Math::abs).sorted().toList();
            Double typical = absolute.isEmpty() ? null : quantile(absolute, 0.5);
            Double p90 = absolute.isEmpty() ? null : quantile(absolute, 0.9);
            Double ratio = p90 == null || delta == null ? null : Math.abs(delta) / Math.max(p90, minShareChange);

            String pairStatus;
            if (!status.equals("COMPARABLE")) {
                pairStatus = status;
            } else if (Math.max(inReference.kept, inCurrent.kept) < minTrips) {
                pairStatus = "LOW_COUNTS";
            } else if (baselineCount < minBaselineTrips) {
                pairStatus = "LOW_BASELINE_COUNTS";
            } else if (Math.abs(delta) < minShareChange) {
                pairStatus = "SMALL_SHARE_CHANGE";
            } else if (ratio < minVariationRatio) {
                pairStatus = "WITHIN_WEEKLY_VARIATION";
            } else {
                pairStatus = "CHANGED";
            }

            Double expected = referenceTotal == 0 ? null : referenceShare * currentTotal;
            // Les semaines et les sources sont ajoutées ensuite, seulement pour les flux renvoyés.
            changes.add(new Change(zones.get(key.origin()), zones.get(key.destination()),
                    inReference.counts(), inCurrent.counts(), List.of(), List.of(), referenceShare, currentShare, delta,
                    delta == null ? null : 100 * delta,
                    referenceShare == null || referenceShare == 0 || delta == null ? null : delta / referenceShare,
                    expected,
                    expected == null ? null : expected - inReference.kept,
                    expected == null ? null : inCurrent.kept - expected,
                    pairStatus, typical, p90, ratio, List.of(), adjacent));
        }

        Comparator<Change> byLargestChange = Comparator
                .<Change>comparingDouble(c -> c.shareChange() == null ? -1 : Math.abs(c.shareChange())).reversed()
                .thenComparingInt(c -> c.origin().id())
                .thenComparingInt(c -> c.destination().id());
        changes.sort(byLargestChange);

        var qualified = changes.stream().filter(c -> c.status().equals("CHANGED")).toList();
        UnaryOperator<Change> details = c -> withDetails(c, pairs.get(new Pair(c.origin().id(), c.destination().id())),
                referenceFrom, referenceTo, from, to, history, imports);
        var increases = qualified.stream().filter(c -> c.shareChange() > 0).limit(limit).map(details).toList();
        var decreases = qualified.stream().filter(c -> c.shareChange() < 0).limit(limit).map(details).toList();
        var others = changes.stream().filter(c -> !c.status().equals("CHANGED")).limit(limit).map(details).toList();

        return new Response(area.stream().map(zones::get).toList(),
                "Tous les départs retenus de l'aire, trajets internes compris.",
                "data.tpep_pickup_datetime", "flows", QualityProfiles.FLOWS,
                new Rules(minTrips, minBaselineTrips, minTotalTrips, minBaselineWeeks, minShareChange, minVariationRatio, limit),
                referencePeriod, currentPeriod, history, status,
                referenceTotal == 0 ? null : (double) currentTotal / referenceTotal - 1,
                changes.size(), qualified.size(), increases, decreases, others, files,
                "Flux filtrés par effectifs, variation de part et ratio au p90 hebdomadaire, puis triés par variation absolue de part.",
                "Comparaison descriptive, pas un test statistique. Les parts sont des fractions. Les semaines fériées sont signalées, pas neutralisées.");
    }

    private static String globalStatus(Period reference, Period current, Period history, int minBaselineWeeks) {
        if (reference.weeks().stream().anyMatch(w -> !w.usable()) || current.weeks().stream().anyMatch(w -> !w.usable())) {
            return "INCOMPLETE_OR_LOW_VOLUME_PERIOD";
        }
        var validWeeks = history.weeks().stream().filter(Week::usable).map(Week::start).toList();
        int differences = (int) validWeeks.stream().filter(w -> validWeeks.contains(w.minusWeeks(1))).count();
        if (validWeeks.size() < minBaselineWeeks || differences < minBaselineWeeks - 1) {
            return "INSUFFICIENT_BASELINE";
        }
        return "COMPARABLE";
    }

    private static boolean fullWeeks(LocalDate from, LocalDate to) {
        return from.isBefore(to) && from.getDayOfWeek() == DayOfWeek.MONDAY && to.getDayOfWeek() == DayOfWeek.MONDAY;
    }

    private static Change withDetails(Change c, Map<LocalDate, Counter> values, LocalDate referenceFrom, LocalDate referenceTo,
            LocalDate from, LocalDate to, Period history, List<Document> imports) {
        var weeks = new ArrayList<PairWeek>();
        for (var week : history.weeks()) {
            var counter = values.getOrDefault(week.start(), new Counter());
            Double share = week.usable() ? (double) counter.kept / week.counts().retained() : null;
            weeks.add(new PairWeek(week.start(), counter.counts(), week.counts().retained(), share, counter.sources(imports)));
        }
        return new Change(c.origin(), c.destination(), c.referenceCounts(), c.currentCounts(),
                sum(values, referenceFrom, referenceTo).sources(imports), sum(values, from, to).sources(imports),
                c.referenceShare(), c.currentShare(), c.shareChange(), c.percentagePointChange(), c.relativeShareChange(),
                c.expectedCurrentAtReferenceShare(), c.volumeOnlyCountChange(), c.residualCountChange(), c.status(),
                c.typicalWeeklyChange(), c.p90WeeklyChange(), c.variationRatio(), weeks, c.adjacentWeeklyChanges());
    }

    private static double quantile(List<Double> sorted, double p) {
        double position = (sorted.size() - 1) * p;
        int below = (int) position;
        int above = (int) Math.ceil(position);
        return sorted.get(below) + (sorted.get(above) - sorted.get(below)) * (position - below);
    }

    private static Counter sum(Map<LocalDate, Counter> values, LocalDate from, LocalDate to) {
        var total = new Counter();
        for (var week = from; week.isBefore(to); week = week.plusWeeks(1)) {
            total.add(values.getOrDefault(week, new Counter()));
        }
        return total;
    }

    private static Period period(LocalDate from, LocalDate to, Map<LocalDate, Counter> totals, List<String> months,
            int minTotal, List<Document> imports) {
        var weeks = new ArrayList<Week>();
        for (var week = from; week.isBefore(to); week = week.plusWeeks(1)) {
            var warnings = new ArrayList<String>();
            for (var day = week; day.isBefore(week.plusWeeks(1)); day = day.plusDays(1)) {
                if (!months.contains(YearMonth.from(day).toString()) && !warnings.contains("SOURCE_MONTH_MISSING")) {
                    warnings.add("SOURCE_MONTH_MISSING");
                }
                if (Calendar2024.holiday(day) != null) {
                    warnings.add("HOLIDAY: " + day + " " + Calendar2024.holiday(day));
                }
                if (Calendar2024.transition(day)) {
                    warnings.add("DST_WEEK: " + day);
                }
            }
            var counter = totals.getOrDefault(week, new Counter());
            if (counter.kept < minTotal) {
                warnings.add("LOW_WEEK_TOTAL");
            }
            boolean usable = !warnings.contains("SOURCE_MONTH_MISSING") && counter.kept >= minTotal;
            weeks.add(new Week(week, counter.counts(), counter.sources(imports), usable, warnings));
        }
        var total = sum(totals, from, to);
        return new Period(from, to, total.counts(), total.sources(imports), weeks);
    }
}
