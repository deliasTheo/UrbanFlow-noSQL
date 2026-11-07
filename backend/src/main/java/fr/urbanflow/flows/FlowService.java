package fr.urbanflow.flows;

import fr.urbanflow.Counts;
import fr.urbanflow.QualityProfiles;
import fr.urbanflow.Zone;
import fr.urbanflow.activity.ActivityRepository;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.temporal.TemporalAdjusters;
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
public class FlowService {
    private final ActivityRepository reference;
    private final FlowRepository repository;

    public FlowService(ActivityRepository reference, FlowRepository repository) {
        this.reference = reference;
        this.repository = repository;
    }

    public record Week(LocalDate start, boolean completeWeek, Counts counts) {}

    public record Source(String fileId, String fileName, String month, Counts counts) {}

    public record Destination(Zone zone, Counts counts, double share, List<Source> sources) {}

    public record Flow(Zone origin, Zone destination, Counts counts, double share,
            boolean internalToSameZone, Long reverseRetained, Double directionalBalance,
            String pattern, int qualifyingWeeks, int referenceWeeks, Double peakWeekShare,
            List<Week> weeks, List<Source> sources, List<Source> reverseSources) {}

    public record Rules(int minTrips, int minWeeklyTrips, double regularFraction, double peakShare,
            int minimumReferenceWeeks) {}

    public record Response(List<Zone> area, LocalDate from, LocalDate to, String timezone,
            String timeField, String profile, List<String> excludedFlags, Rules rules, Counts totals,
            long eligiblePairs, long belowMinTripsPairs, List<Destination> destinations,
            List<Flow> pairs, List<Source> sources, List<String> missingSourceMonths, String note) {}

    private record Pair(int origin, int destination) {}

    private static class Counter {
        long raw;
        long retained;

        void add(long raw, long retained) {
            this.raw += raw;
            this.retained += retained;
        }

        void add(Counter other) {
            add(other.raw, other.retained);
        }

        Counts counts() {
            return new Counts(raw, retained, raw - retained);
        }
    }

    private static class Accumulator extends Counter {
        final Map<LocalDate, Counter> weeks = new TreeMap<>();
        final Map<String, Counter> sources = new TreeMap<>();

        long retainedIn(LocalDate week) {
            return weeks.getOrDefault(week, new Counter()).retained;
        }
    }

    public Response flows(List<Integer> zoneIds, String borough, LocalDate from, LocalDate to,
            int limit, int minTrips, int minWeeklyTrips, double regularFraction, double peakShare) {
        boolean hasZones = zoneIds != null && !zoneIds.isEmpty();
        boolean hasBorough = borough != null && !borough.isBlank();
        boolean invalidRules = limit < 1 || limit > 100 || minTrips < 1 || minWeeklyTrips < 1
                || !Double.isFinite(regularFraction) || regularFraction <= 0 || regularFraction > 1
                || !Double.isFinite(peakShare) || peakShare <= 0 || peakShare > 1;
        if ((hasZones && zoneIds.stream().anyMatch(Objects::isNull)) || hasZones == hasBorough || !from.isBefore(to) || invalidRules) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Choisir zoneIds OU borough, début < fin, limit 1..100, seuils entiers positifs et fractions dans ]0,1].");
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

        var missing = new ArrayList<String>();
        var months = imports.stream().map(d -> d.getString("file_month")).toList();
        for (var month = YearMonth.from(from); !month.isAfter(YearMonth.from(to.minusDays(1))); month = month.plusMonths(1)) {
            if (!months.contains(month.toString())) {
                missing.add(month.toString());
            }
        }

        var weeks = new ArrayList<LocalDate>();
        for (var week = from.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)); week.isBefore(to); week = week.plusWeeks(1)) {
            weeks.add(week);
        }
        var fullWeeks = weeks.stream().filter(w -> !w.isBefore(from) && !w.plusWeeks(1).isAfter(to)).toList();

        var all = new HashMap<Pair, Accumulator>();
        for (var row : repository.flows(new ArrayList<>(area), from, to, files)) {
            var id = row.get("_id", Document.class);
            var key = new Pair(((Number) id.get("origin")).intValue(), ((Number) id.get("destination")).intValue());
            var pair = all.computeIfAbsent(key, k -> new Accumulator());
            long raw = ((Number) row.get("raw")).longValue();
            long kept = ((Number) row.get("retained")).longValue();
            pair.add(raw, kept);
            pair.weeks.computeIfAbsent(LocalDate.parse(id.getString("week")), k -> new Counter()).add(raw, kept);
            pair.sources.computeIfAbsent(id.getString("source"), k -> new Counter()).add(raw, kept);
        }

        // Le pipeline lit aussi les retours : seuls les départs de l'aire comptent dans les totaux.
        var outgoing = all.entrySet().stream().filter(e -> area.contains(e.getKey().origin())).toList();
        var total = new Accumulator();
        var destinations = new TreeMap<Integer, Accumulator>();
        for (var entry : outgoing) {
            var pair = entry.getValue();
            total.add(pair);
            pair.sources.forEach((file, counter) -> total.sources.computeIfAbsent(file, k -> new Counter()).add(counter));
            var destination = destinations.computeIfAbsent(entry.getKey().destination(), k -> new Accumulator());
            destination.add(pair);
            pair.sources.forEach((file, counter) -> destination.sources.computeIfAbsent(file, k -> new Counter()).add(counter));
        }

        Comparator<Map.Entry<Pair, Accumulator>> ranking = Comparator
                .<Map.Entry<Pair, Accumulator>>comparingLong(e -> e.getValue().retained).reversed()
                .thenComparingInt(e -> e.getKey().origin())
                .thenComparingInt(e -> e.getKey().destination());
        var eligible = outgoing.stream().filter(e -> e.getValue().retained >= minTrips).sorted(ranking).toList();

        var top = eligible.stream().limit(limit).map(entry -> {
            var key = entry.getKey();
            var pair = entry.getValue();
            long fullTotal = fullWeeks.stream().mapToLong(pair::retainedIn).sum();
            long peak = fullWeeks.stream().mapToLong(pair::retainedIn).max().orElse(0);
            int qualifying = (int) fullWeeks.stream().filter(w -> pair.retainedIn(w) >= minWeeklyTrips).count();
            Double concentration = fullTotal == 0 ? null : (double) peak / fullTotal;

            String pattern;
            if (!missing.isEmpty() || fullWeeks.size() < 3) {
                pattern = "insufficient_history";
            } else if ((double) qualifying / fullWeeks.size() >= regularFraction) {
                pattern = "regular";
            } else if (concentration != null && peak >= minWeeklyTrips && concentration >= peakShare) {
                pattern = "peak";
            } else {
                pattern = "variable";
            }

            boolean self = key.origin() == key.destination();
            var opposite = all.getOrDefault(new Pair(key.destination(), key.origin()), new Accumulator());
            long reverse = opposite.retained;
            var weekly = weeks.stream()
                    .map(w -> new Week(w, fullWeeks.contains(w), pair.weeks.getOrDefault(w, new Counter()).counts()))
                    .toList();
            return new Flow(zones.get(key.origin()), zones.get(key.destination()), pair.counts(),
                    share(pair.retained, total.retained), self,
                    self ? null : reverse,
                    self ? null : (double) (pair.retained - reverse) / (pair.retained + reverse),
                    pattern, qualifying, fullWeeks.size(), concentration, weekly,
                    sources(pair, imports),
                    self ? List.of() : sources(opposite, imports));
        }).toList();

        var topDestinations = destinations.entrySet().stream()
                .filter(e -> e.getValue().retained >= minTrips)
                .sorted(Comparator.<Map.Entry<Integer, Accumulator>>comparingLong(e -> e.getValue().retained).reversed()
                        .thenComparingInt(Map.Entry::getKey))
                .limit(limit)
                .map(e -> new Destination(zones.get(e.getKey()), e.getValue().counts(),
                        share(e.getValue().retained, total.retained), sources(e.getValue(), imports)))
                .toList();

        return new Response(area.stream().map(zones::get).toList(), from, to, "America/New_York",
                "data.tpep_pickup_datetime", "flows", QualityProfiles.FLOWS,
                new Rules(minTrips, minWeeklyTrips, regularFraction, peakShare, 3), total.counts(),
                eligible.size(), outgoing.stream().filter(e -> e.getValue().retained < minTrips).count(),
                topDestinations, top, sources(total, imports), missing,
                "Les parts portent sur tous les départs retenus de l'aire, trajets internes compris. Les semaines partielles ne comptent pas dans la classification.");
    }

    private static double share(long count, long total) {
        return total == 0 ? 0 : (double) count / total;
    }

    private static List<Source> sources(Accumulator accumulator, List<Document> imports) {
        return imports.stream().map(d -> new Source(d.getString("_id"), d.getString("file_name"), d.getString("file_month"),
                accumulator.sources.getOrDefault(d.getString("_id"), new Counter()).counts())).toList();
    }
}
