package fr.urbanflow.journeys;

import fr.urbanflow.activity.ActivityRepository;
import java.time.*;
import java.util.*;
import org.bson.Document;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class JourneyService {
    public static final List<String> ACTIVITY=List.of("NEGATIVE_AMOUNT","EXACT_DUPLICATE");
    public static final List<String> JOURNEY=List.of("NEGATIVE_AMOUNT","EXACT_DUPLICATE","UNKNOWN_ZONE","NON_POSITIVE_DURATION",
        "EXCESSIVE_DURATION","ZERO_DISTANCE","IMPLAUSIBLE_DISTANCE","IMPLAUSIBLE_SPEED","DST_UNRESOLVED");
    private static final long MAX_ROWS=200000;
    private final ActivityRepository reference;
    private final JourneyRepository repository;
    public JourneyService(ActivityRepository reference,JourneyRepository repository) { this.reference=reference;this.repository=repository; }
    public record Zone(int id,String borough,String name) {}
    public record Metric(long count,long missing,Double min,Double q25,Double median,Double q75,Double p90,Double max,
        Double mean,Double populationStdDev,Double iqr,long iqrOutliers) {}
    public record Statistics(long records,Metric durationSeconds,Metric distanceMiles) {}
    public record Source(String fileId,String fileName,long raw,long retained,long lessReliable,long activityExcluded) {}
    public record Stratum(String key,Statistics stats) {}
    public record Period(LocalDate from,LocalDate to,long raw,long retained,long lessReliable,long activityExcluded,
        long dstSpanningRetained,Statistics usable,Statistics unreliable,List<Stratum> strata,Map<String,Long> exclusionReasons,List<Source> sources,
        List<String> missingSourceMonths) {}
    public record Comparison(String status,Double durationMedianDifferenceSeconds,Double distanceMedianDifferenceMiles,
        int commonStrata,long referenceCommonRecords,long currentCommonRecords,Double referenceCommonFraction,Double currentCommonFraction,
        Double standardizedReferenceDurationSeconds,Double standardizedCurrentDurationSeconds,Double standardizedDurationDifferenceSeconds,String method) {}
    public record Response(Zone origin,Zone destination,String timezone,String timeField,String profile,List<String> excludedFlags,
        int minTrips,Period reference,Period current,Comparison comparison,String note) {}
    private static class Values {
        long records;
        final List<Double> durations=new ArrayList<>(),distances=new ArrayList<>();
        void add(Document d) { records++;addNumber(d.get("duration"),durations);addNumber(d.get("distance"),distances); }
        Statistics stats() { return new Statistics(records,metric(durations,records),metric(distances,records)); }
    }
    private static class Accumulator {
        long raw,kept,less,activityExcluded,dst;
        final Values usable=new Values(),unreliable=new Values();
        final Map<String,Values> strata=new TreeMap<>();
        final Map<String,long[]> sources=new TreeMap<>();
        final Map<String,Long> reasons=new TreeMap<>();
        void add(Document d) {
            raw++;var source=sources.computeIfAbsent(d.getString("source"),k -> new long[4]);source[0]++;
            var flags=d.getList("flags",String.class,List.of());
            for (String flag:JOURNEY) if (flags.contains(flag)) reasons.merge(flag,1L,Long::sum);
            if (flags.stream().anyMatch(ACTIVITY::contains)) { activityExcluded++;source[3]++;return; }
            if (flags.stream().anyMatch(JOURNEY::contains)) { less++;source[2]++;unreliable.add(d);return; }
            kept++;source[1]++;usable.add(d);
            if (flags.contains("DST_SPANNING")) dst++;
            int hour=((Number)d.get("hour")).intValue(),weekday=((Number)d.get("weekday")).intValue();
            double distance=d.get("distance") instanceof Number n ? n.doubleValue() : Double.NaN;
            String key=(weekday>=6?"weekend":"weekday")+"_h"+(hour/6*6)+"_mi"+(!Double.isFinite(distance)?"missing":distance<2?"0-2":distance<5?"2-5":distance<10?"5-10":"10+");
            strata.computeIfAbsent(key,k -> new Values()).add(d);
        }
        Period period(LocalDate from,LocalDate to,List<Document> imports) {
            var known=imports.stream().map(d -> d.getString("file_month")).toList();var missing=new ArrayList<String>();
            for (var m=YearMonth.from(from);!m.isAfter(YearMonth.from(to.minusDays(1)));m=m.plusMonths(1)) if(!known.contains(m.toString())) missing.add(m.toString());
            return new Period(from,to,raw,kept,less,activityExcluded,dst,usable.stats(),unreliable.stats(),
                strata.entrySet().stream().map(e -> new Stratum(e.getKey(),e.getValue().stats())).toList(),new TreeMap<>(reasons),
                imports.stream().map(d -> {var c=sources.getOrDefault(d.getString("_id"),new long[4]);return new Source(d.getString("_id"),d.getString("file_name"),c[0],c[1],c[2],c[3]);}).toList(),missing);
        }
    }
    public Response compare(int originId,int destinationId,LocalDate from,LocalDate to,LocalDate referenceFrom,LocalDate referenceTo,int minTrips) {
        if (!from.isBefore(to)||!referenceFrom.isBefore(referenceTo)||referenceTo.isAfter(from)||minTrips<2)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Intervalles non vides, référence antérieure sans chevauchement et minTrips >= 2 requis.");
        var origin=reference.zone(originId);var destination=reference.zone(destinationId);
        if (origin==null||destination==null) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Zone inconnue.");
        var imports=reference.completeImports();
        if (imports.isEmpty()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"Aucun import complet disponible.");
        imports.sort(Comparator.comparing(d -> d.getString("_id")));
        var a=new Accumulator();var b=new Accumulator();long count=0;
        try (var rows=repository.rows(originId,destinationId,from,to,referenceFrom,referenceTo,imports.stream().map(d -> d.getString("_id")).toList())) {
            var iterator=rows.iterator();
            while(iterator.hasNext()) {
                if (++count>MAX_ROWS) throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,"Plus de 200 000 lignes candidates : réduire les intervalles pour les quantiles exacts. Aucun résultat partiel fourni.");
                var d=iterator.next();(d.getString("period").equals("reference")?a:b).add(d);
            }
        }
        var pa=a.period(referenceFrom,referenceTo,imports);var pb=b.period(from,to,imports);
        var keys=new TreeSet<>(a.strata.keySet());keys.retainAll(b.strata.keySet());
        keys.removeIf(k -> a.strata.get(k).durations.size()<minTrips||b.strata.get(k).durations.size()<minTrips);
        long na=keys.stream().mapToLong(k -> a.strata.get(k).records).sum(),nb=keys.stream().mapToLong(k -> b.strata.get(k).records).sum();
        double sa=0,sb=0;
        for (String key:keys) {
            double w=(double)a.strata.get(key).records/na;
            sa+=w*a.strata.get(key).stats().durationSeconds().mean();sb+=w*b.strata.get(key).stats().durationSeconds().mean();
        }
        String status=!pa.missingSourceMonths().isEmpty()||!pb.missingSourceMonths().isEmpty()?"SOURCE_MONTH_MISSING"
            :a.usable.durations.size()<minTrips||b.usable.durations.size()<minTrips?"INSUFFICIENT_SAMPLE":keys.isEmpty()?"NO_COMMON_STRATA":"COMPARABLE";
        boolean enough=a.usable.durations.size()>=minTrips&&b.usable.durations.size()>=minTrips,
            enoughDistance=a.usable.distances.size()>=minTrips&&b.usable.distances.size()>=minTrips,comparable=status.equals("COMPARABLE");
        var comparison=new Comparison(status,enough?pb.usable().durationSeconds().median()-pa.usable().durationSeconds().median():null,
            enoughDistance?pb.usable().distanceMiles().median()-pa.usable().distanceMiles().median():null,keys.size(),na,nb,
            a.kept==0?null:(double)na/a.kept,b.kept==0?null:(double)nb/b.kept,
            comparable?sa:null,comparable?sb:null,comparable?sb-sa:null,
            "Strates jour ouvré/week-end × créneau de 6 h × distance [0,2[, [2,5[, [5,10[, [10,+inf[ miles. Même poids de référence parmi les strates au seuil dans les deux périodes ; moyennes pondérées, pas médianes standardisées.");
        return new Response(zone(origin),zone(destination),"America/New_York","data.tpep_pickup_datetime","journey",JOURNEY,minTrips,pa,pb,comparison,
            "Quantiles exacts par interpolation linéaire (n-1)*p. Durées en secondes, distances en miles. Les moins fiables excluent les montants négatifs/doublons ; leurs valeurs numériques peuvent être aberrantes. Seuil IQR descriptif sans suppression supplémentaire. Les différences ne prouvent pas une cause, les jours fériés ne sont pas neutralisés. Mois complets ne garantit pas une couverture complète. Limite 200 000 candidats pour la mémoire.");
    }
    private static Zone zone(Document d) { return new Zone(((Number)d.get("_id")).intValue(),d.getString("Borough"),d.getString("Zone")); }
    private static void addNumber(Object value,List<Double> target) { if (value instanceof Number n&&Double.isFinite(n.doubleValue())) target.add(n.doubleValue()); }
    private static double quantile(List<Double> x,double p) { double at=(x.size()-1)*p;int i=(int)at;return x.get(i)+(x.get((int)Math.ceil(at))-x.get(i))*(at-i); }
    private static Metric metric(List<Double> values,long total) {
        var x=values.stream().sorted().toList();int n=x.size();
        if(n==0) return new Metric(0,total,null,null,null,null,null,null,null,null,null,0);
        double q25=quantile(x,0.25),q75=quantile(x,0.75),iqr=q75-q25,mean=x.stream().mapToDouble(Double::doubleValue).average().orElseThrow();
        double variance=x.stream().mapToDouble(v -> (v-mean)*(v-mean)).average().orElseThrow();
        long outliers=x.stream().filter(v -> v<q25-1.5*iqr||v>q75+1.5*iqr).count();
        return new Metric(n,total-n,x.getFirst(),q25,quantile(x,0.5),q75,quantile(x,0.9),x.getLast(),mean,Math.sqrt(variance),iqr,outliers);
    }
}
