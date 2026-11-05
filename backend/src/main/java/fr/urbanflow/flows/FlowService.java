package fr.urbanflow.flows;

import fr.urbanflow.activity.ActivityRepository;
import java.time.*;
import java.time.temporal.TemporalAdjusters;
import java.util.*;
import org.bson.Document;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class FlowService {
    private final ActivityRepository reference;
    private final FlowRepository repository;
    public FlowService(ActivityRepository reference, FlowRepository repository) {
        this.reference = reference; this.repository = repository;
    }
    public record Counts(long raw, long retained, long excluded) {}
    public record Zone(int id, String borough, String name) {}
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
        long raw, retained;
        void add(long r, long n) { raw += r; retained += n; }
        void add(Counter c) { add(c.raw, c.retained); }
        Counts counts() { return new Counts(raw, retained, raw-retained); }
    }
    private static class Accumulator extends Counter {
        final Map<LocalDate, Counter> weeks = new TreeMap<>();
        final Map<String, Counter> sources = new TreeMap<>();
    }

    public Response flows(List<Integer> zoneIds, String borough, LocalDate from, LocalDate to,
            int limit, int minTrips, int minWeeklyTrips, double regularFraction, double peakShare) {
        boolean hasZones = zoneIds != null && !zoneIds.isEmpty();
        boolean hasBorough = borough != null && !borough.isBlank();
        if ((hasZones && zoneIds.stream().anyMatch(Objects::isNull)) || hasZones == hasBorough || !from.isBefore(to) || limit < 1 || limit > 100 || minTrips < 1
                || minWeeklyTrips < 1 || !Double.isFinite(regularFraction) || regularFraction <= 0 || regularFraction > 1
                || !Double.isFinite(peakShare) || peakShare <= 0 || peakShare > 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Choisir zoneIds OU borough, début < fin, limit 1..100, seuils entiers positifs et fractions dans ]0,1].");
        }
        var zones = new TreeMap<Integer, Zone>();
        reference.zones().forEach(d -> {
            int id = ((Number)d.get("_id")).intValue();
            zones.put(id, new Zone(id, d.getString("Borough"), d.getString("Zone")));
        });
        var area = new TreeSet<Integer>();
        if (hasZones) {
            for (int id : zoneIds) {
                if (!zones.containsKey(id)) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Zone inconnue : " + id);
                area.add(id);
            }
        } else {
            zones.values().stream().filter(z -> borough.trim().equalsIgnoreCase(z.borough())).forEach(z -> area.add(z.id()));
            if (area.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Borough inconnu.");
        }
        var imports = reference.completeImports();
        if (imports.isEmpty()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Aucun import complet disponible.");
        imports.sort(Comparator.comparing(d -> d.getString("_id")));
        var files = imports.stream().map(d -> d.getString("_id")).toList();
        var missing = new ArrayList<String>();
        var months = imports.stream().map(d -> d.getString("file_month")).toList();
        for (var m = YearMonth.from(from); !m.isAfter(YearMonth.from(to.minusDays(1))); m=m.plusMonths(1))
            if (!months.contains(m.toString())) missing.add(m.toString());
        var weeks = new ArrayList<LocalDate>();
        for (var w=from.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)); w.isBefore(to); w=w.plusWeeks(1)) weeks.add(w);
        var fullWeeks = weeks.stream().filter(w -> !w.isBefore(from) && !w.plusWeeks(1).isAfter(to)).toList();
        var all = new HashMap<Pair, Accumulator>();
        for (var d : repository.flows(new ArrayList<>(area), from, to, files)) {
            var id = d.get("_id", Document.class);
            var key = new Pair(((Number)id.get("origin")).intValue(), ((Number)id.get("destination")).intValue());
            var a = all.computeIfAbsent(key, k -> new Accumulator());
            long raw=((Number)d.get("raw")).longValue(), kept=((Number)d.get("retained")).longValue();
            a.add(raw, kept);
            a.weeks.computeIfAbsent(LocalDate.parse(id.getString("week")), k -> new Counter()).add(raw, kept);
            a.sources.computeIfAbsent(id.getString("source"), k -> new Counter()).add(raw, kept);
        }
        var outgoing = all.entrySet().stream().filter(e -> area.contains(e.getKey().origin())).toList();
        var total = new Accumulator();
        var destinations = new TreeMap<Integer, Accumulator>();
        for (var e : outgoing) {
            total.add(e.getValue());
            e.getValue().sources.forEach((s,c) -> total.sources.computeIfAbsent(s, k -> new Counter()).add(c));
            var destination = destinations.computeIfAbsent(e.getKey().destination(), k -> new Accumulator());
            destination.add(e.getValue());
            e.getValue().sources.forEach((s,c) -> destination.sources.computeIfAbsent(s, k -> new Counter()).add(c));
        }
        Comparator<Map.Entry<Pair, Accumulator>> ranking = Comparator
                .<Map.Entry<Pair, Accumulator>>comparingLong(e -> e.getValue().retained).reversed()
                .thenComparingInt(e -> e.getKey().origin()).thenComparingInt(e -> e.getKey().destination());
        var eligible=outgoing.stream().filter(e -> e.getValue().retained >= minTrips).sorted(ranking).toList();
        var top = eligible.stream().limit(limit).map(e -> {
            var key=e.getKey(); var a=e.getValue();
            long fullTotal=fullWeeks.stream().mapToLong(w -> a.weeks.getOrDefault(w,new Counter()).retained).sum();
            long peak=fullWeeks.stream().mapToLong(w -> a.weeks.getOrDefault(w,new Counter()).retained).max().orElse(0);
            int qualifying=(int)fullWeeks.stream().filter(w -> a.weeks.getOrDefault(w,new Counter()).retained >= minWeeklyTrips).count();
            Double concentration=fullTotal==0 ? null : (double)peak/fullTotal;
            String pattern = !missing.isEmpty() || fullWeeks.size()<3 ? "insufficient_history"
                    : (double)qualifying/fullWeeks.size() >= regularFraction ? "regular"
                    : concentration!=null && peak>=minWeeklyTrips && concentration>=peakShare ? "peak" : "variable";
            boolean self=key.origin()==key.destination();
            long reverse=all.getOrDefault(new Pair(key.destination(),key.origin()),new Accumulator()).retained;
            return new Flow(zones.get(key.origin()), zones.get(key.destination()), a.counts(), share(a.retained,total.retained),
                    self, self ? null : reverse, self ? null : (double)(a.retained-reverse)/(a.retained+reverse),
                    pattern, qualifying, fullWeeks.size(), concentration,
                    weeks.stream().map(w -> new Week(w, fullWeeks.contains(w), a.weeks.getOrDefault(w,new Counter()).counts())).toList(),
                    sources(a, imports), self ? List.of() : sources(all.getOrDefault(new Pair(key.destination(),key.origin()), new Accumulator()), imports));
        }).toList();
        var dest=destinations.entrySet().stream().filter(e -> e.getValue().retained>=minTrips)
                .sorted(Comparator.<Map.Entry<Integer,Accumulator>>comparingLong(e -> e.getValue().retained).reversed().thenComparingInt(Map.Entry::getKey))
                .limit(limit).map(e -> new Destination(zones.get(e.getKey()), e.getValue().counts(), share(e.getValue().retained,total.retained), sources(e.getValue(),imports))).toList();
        return new Response(area.stream().map(zones::get).toList(),from,to,"America/New_York","data.tpep_pickup_datetime",
                "flows",FlowRepository.EXCLUDED,new Rules(minTrips,minWeeklyTrips,regularFraction,peakShare,3),total.counts(),
                eligible.size(),outgoing.stream().filter(e -> e.getValue().retained<minTrips).count(),dest,top,sources(total,imports),missing,
                "Totaux et parts : tous les départs de l'aire retenus, avant limite/seuil. Les trajets internes à l'aire sont inclus. Sens inverse : mêmes dates de départ, même profil, sans seuil. Semaines partielles exclues de la classification. Couverture par mois source indicative ; aucune causalité ni demande non satisfaite déduite.");
    }
    private static double share(long n,long total) { return total==0 ? 0 : (double)n/total; }
    private static List<Source> sources(Accumulator a,List<Document> imports) {
        return imports.stream().map(d -> new Source(d.getString("_id"),d.getString("file_name"),d.getString("file_month"),
                a.sources.getOrDefault(d.getString("_id"),new Counter()).counts())).toList();
    }
}
