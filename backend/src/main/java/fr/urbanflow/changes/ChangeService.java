package fr.urbanflow.changes;

import fr.urbanflow.activity.ActivityRepository;
import fr.urbanflow.unusual.Calendar2024;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import org.bson.Document;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ChangeService {
    private final ActivityRepository reference;
    private final ChangeRepository repository;
    public ChangeService(ActivityRepository reference,ChangeRepository repository) { this.reference=reference;this.repository=repository; }
    public record Counts(long raw,long retained,long excluded) {}
    public record Source(String fileId,String fileName,Counts counts) {}
    public record Zone(int id,String borough,String name) {}
    public record Week(LocalDate start,Counts counts,List<Source> sources,boolean usable,List<String> warnings) {}
    public record Period(LocalDate from,LocalDate to,Counts counts,List<Source> sources,List<Week> weeks) {}
    public record PairWeek(LocalDate start,Counts counts,long denominator,Double share,List<Source> sources) {}
    public record Change(Zone origin,Zone destination,Counts referenceCounts,Counts currentCounts,
        List<Source> referenceSources,List<Source> currentSources,Double referenceShare,Double currentShare,
        Double shareChange,Double percentagePointChange,Double relativeShareChange,Double expectedCurrentAtReferenceShare,
        Double volumeOnlyCountChange,Double residualCountChange,String status,Double typicalWeeklyChange,
        Double p90WeeklyChange,Double variationRatio,List<PairWeek> baselineWeeks,List<Double> adjacentWeeklyChanges) {}
    public record Rules(int minTrips,int minBaselineTrips,int minTotalTrips,int minBaselineWeeks,double minShareChange,double minVariationRatio,int limit) {}
    public record Response(List<Zone> area,String denominator,String timeField,String profile,List<String> excludedFlags,Rules rules,
        Period reference,Period current,Period baseline,String status,Double totalVolumeChange,long pairsConsidered,long qualifiedPairs,
        List<Change> increases,List<Change> decreases,List<Change> otherLargestChanges,List<String> sourceFiles,String ranking,String note) {}
    private record Pair(int origin,int destination) {}
    private static class Counter {
        long raw,kept;
        final Map<String,long[]> files=new TreeMap<>();
        void add(String file,long raw,long kept) { this.raw+=raw;this.kept+=kept;var c=files.computeIfAbsent(file,k -> new long[2]);c[0]+=raw;c[1]+=kept; }
        void add(Counter c) { c.files.forEach((f,n) -> add(f,n[0],n[1])); }
        Counts counts() { return new Counts(raw,kept,raw-kept); }
        List<Source> sources(List<Document> imports) {
            return imports.stream().map(d -> {var c=files.getOrDefault(d.getString("_id"),new long[2]);return new Source(d.getString("_id"),d.getString("file_name"),new Counts(c[0],c[1],c[0]-c[1]));}).toList();
        }
    }
    public Response compare(List<Integer> zoneIds,String borough,LocalDate from,LocalDate to,LocalDate referenceFrom,LocalDate referenceTo,
        LocalDate baselineFrom,LocalDate baselineTo,int minTrips,int minBaselineTrips,int minTotalTrips,int minBaselineWeeks,
        double minShareChange,double minVariationRatio,int limit) {
        boolean hasZones=zoneIds!=null&&!zoneIds.isEmpty(),hasBorough=borough!=null&&!borough.isBlank();
        if ((hasZones&&hasBorough)||(hasZones&&zoneIds.stream().anyMatch(Objects::isNull)) || !fullWeeks(from,to)||!fullWeeks(referenceFrom,referenceTo)
            || !fullWeeks(baselineFrom,baselineTo)||referenceTo.isAfter(from)||baselineTo.isAfter(from)
            || ChronoUnit.DAYS.between(from,to)!=ChronoUnit.DAYS.between(referenceFrom,referenceTo)
            || minTrips<1||minBaselineTrips<1||minTotalTrips<1||minBaselineWeeks<3||limit<1||limit>100
            || !Double.isFinite(minShareChange)||minShareChange<=0||minShareChange>1||!Double.isFinite(minVariationRatio)||minVariationRatio<1
            || List.of(from,referenceFrom,baselineFrom).stream().anyMatch(d -> d.getYear()!=2024)
            || List.of(to,referenceTo,baselineTo).stream().anyMatch(d -> d.minusDays(1).getYear()!=2024)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Dates 2024 lundi à lundi ; périodes comparées de même durée, référence et baseline avant la période courante ; seuils positifs, minBaselineWeeks >= 3, ratio >= 1, limit 1..100. zoneIds OU borough ou aucun pour toute la ville.");
        }
        var zones=new TreeMap<Integer,Zone>();reference.zones().forEach(d -> {int id=((Number)d.get("_id")).intValue();zones.put(id,new Zone(id,d.getString("Borough"),d.getString("Zone")));});
        var area=new TreeSet<Integer>();
        if (hasZones) { for(int id:zoneIds) {if(!zones.containsKey(id)) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Zone inconnue : "+id);area.add(id);} }
        else if(hasBorough) {zones.values().stream().filter(z -> borough.trim().equalsIgnoreCase(z.borough())).forEach(z -> area.add(z.id()));if(area.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Borough inconnu.");}
        else area.addAll(zones.keySet());
        var imports=reference.completeImports();if(imports.isEmpty()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"Aucun import complet disponible.");
        imports.sort(Comparator.comparing(d -> d.getString("_id")));var files=imports.stream().map(d -> d.getString("_id")).toList();
        var months=imports.stream().map(d -> d.getString("file_month")).toList();
        var pairs=new HashMap<Pair,Map<LocalDate,Counter>>();var totals=new TreeMap<LocalDate,Counter>();
        for(var row:repository.counts(new ArrayList<>(area),from,to,referenceFrom,referenceTo,baselineFrom,baselineTo,files)) {
            var id=row.get("_id",Document.class);var key=new Pair(((Number)id.get("origin")).intValue(),((Number)id.get("destination")).intValue());var week=LocalDate.parse(id.getString("week"));
            long raw=((Number)row.get("raw")).longValue(),kept=((Number)row.get("retained")).longValue();String file=id.getString("source");
            pairs.computeIfAbsent(key,k -> new TreeMap<>()).computeIfAbsent(week,k -> new Counter()).add(file,raw,kept);
            totals.computeIfAbsent(week,k -> new Counter()).add(file,raw,kept);
        }
        var a=period(referenceFrom,referenceTo,totals,months,minTotalTrips,imports);
        var b=period(from,to,totals,months,minTotalTrips,imports);
        var history=period(baselineFrom,baselineTo,totals,months,minTotalTrips,imports);
        var validWeeks=history.weeks().stream().filter(Week::usable).map(Week::start).toList();
        int differences=(int)validWeeks.stream().filter(w -> validWeeks.contains(w.minusWeeks(1))).count();
        String status=a.weeks().stream().anyMatch(w -> !w.usable())||b.weeks().stream().anyMatch(w -> !w.usable())?"INCOMPLETE_OR_LOW_VOLUME_PERIOD"
            :validWeeks.size()<minBaselineWeeks||differences<minBaselineWeeks-1?"INSUFFICIENT_BASELINE":"COMPARABLE";
        var changes=new ArrayList<Change>();
        for(var entry:pairs.entrySet()) {
            var key=entry.getKey();var values=entry.getValue();var ca=sum(values,referenceFrom,referenceTo);var cb=sum(values,from,to);
            if(ca.kept==0&&cb.kept==0) continue;
            Double pa=a.counts().retained()==0?null:(double)ca.kept/a.counts().retained(),pb=b.counts().retained()==0?null:(double)cb.kept/b.counts().retained(),delta=pa==null||pb==null?null:pb-pa;
            var weeks=new ArrayList<PairWeek>();var shares=new TreeMap<LocalDate,Double>();long baselineCount=0;
            for(var w:history.weeks()) {
                var c=values.getOrDefault(w.start(),new Counter());Double p=w.usable()?(double)c.kept/w.counts().retained():null;
                weeks.add(new PairWeek(w.start(),c.counts(),w.counts().retained(),p,c.sources(imports)));
                if(p!=null) {shares.put(w.start(),p);baselineCount+=c.kept;}
            }
            var adjacent=new ArrayList<Double>();for(var w:shares.keySet()) if(shares.containsKey(w.minusWeeks(1))) adjacent.add(shares.get(w)-shares.get(w.minusWeeks(1)));
            var absolute=adjacent.stream().map(Math::abs).sorted().toList();Double typical=absolute.isEmpty()?null:quantile(absolute,0.5),p90=absolute.isEmpty()?null:quantile(absolute,0.9);
            Double ratio=p90==null||delta==null?null:Math.abs(delta)/Math.max(p90,minShareChange);
            String pairStatus=!status.equals("COMPARABLE")?status:Math.max(ca.kept,cb.kept)<minTrips?"LOW_COUNTS"
                :baselineCount<minBaselineTrips?"LOW_BASELINE_COUNTS":Math.abs(delta)<minShareChange?"SMALL_SHARE_CHANGE"
                :ratio<minVariationRatio?"WITHIN_WEEKLY_VARIATION":"CHANGED";
            Double expected=a.counts().retained()==0?null:pa*b.counts().retained();
            changes.add(new Change(zones.get(key.origin()),zones.get(key.destination()),ca.counts(),cb.counts(),ca.sources(imports),cb.sources(imports),
                pa,pb,delta,delta==null?null:100*delta,pa==null||pa==0||delta==null?null:delta/pa,expected,expected==null?null:expected-ca.kept,expected==null?null:cb.kept-expected,
                pairStatus,typical,p90,ratio,weeks,adjacent));
        }
        Comparator<Change> rank=Comparator.<Change>comparingDouble(c -> (c.shareChange()==null?-1:Math.abs(c.shareChange()))).reversed()
            .thenComparingInt(c -> c.origin().id()).thenComparingInt(c -> c.destination().id());changes.sort(rank);
        var qualified=changes.stream().filter(c -> c.status().equals("CHANGED")).toList();
        return new Response(area.stream().map(zones::get).toList(),"Tous les départs retenus de l'aire sélectionnée ; même périmètre dans les trois intervalles, trajets internes inclus.",
            "data.tpep_pickup_datetime","flows",List.of("NEGATIVE_AMOUNT","EXACT_DUPLICATE","UNKNOWN_ZONE"),
            new Rules(minTrips,minBaselineTrips,minTotalTrips,minBaselineWeeks,minShareChange,minVariationRatio,limit),a,b,history,status,
            a.counts().retained()==0?null:(double)b.counts().retained()/a.counts().retained()-1,changes.size(),qualified.size(),
            qualified.stream().filter(c -> c.shareChange()>0).limit(limit).toList(),qualified.stream().filter(c -> c.shareChange()<0).limit(limit).toList(),
            changes.stream().filter(c -> !c.status().equals("CHANGED")).limit(limit).toList(),files,
            "Filtrer par effectifs, variation absolue minimale de part et ratio au p90 des variations hebdomadaires propres au flux ; trier par variation absolue de part décroissante, puis identifiants croissants.",
            "Comparaison descriptive, aucun test de significativité. Parts en fractions ; percentagePointChange en points. Baseline antérieure à current, peut inclure reference. Zéros historiques locaux inclus si la semaine globale est utilisable. Calendrier signalé, pas neutralisé. Une couverture source apparemment complète ne prouve pas chaque heure complète. Ne pas importer pendant la requête.");
    }
    private static boolean fullWeeks(LocalDate from,LocalDate to) { return from.isBefore(to)&&from.getDayOfWeek()==DayOfWeek.MONDAY&&to.getDayOfWeek()==DayOfWeek.MONDAY; }
    private static double share(long n,long total) {return total==0?0:(double)n/total;}
    private static double quantile(List<Double> x,double p) {double at=(x.size()-1)*p;int i=(int)at;return x.get(i)+(x.get((int)Math.ceil(at))-x.get(i))*(at-i);}
    private static Counter sum(Map<LocalDate,Counter> values,LocalDate from,LocalDate to) {var c=new Counter();for(var w=from;w.isBefore(to);w=w.plusWeeks(1)) c.add(values.getOrDefault(w,new Counter()));return c;}
    private static Period period(LocalDate from,LocalDate to,Map<LocalDate,Counter> totals,List<String> months,int minTotal,List<Document> imports) {
        var weeks=new ArrayList<Week>();for(var w=from;w.isBefore(to);w=w.plusWeeks(1)) {
            var warnings=new ArrayList<String>();for(var d=w;d.isBefore(w.plusWeeks(1));d=d.plusDays(1)) {
                if(!months.contains(YearMonth.from(d).toString())&&!warnings.contains("SOURCE_MONTH_MISSING")) warnings.add("SOURCE_MONTH_MISSING");
                if(Calendar2024.holiday(d)!=null) warnings.add("HOLIDAY: "+d+" "+Calendar2024.holiday(d));
                if(Calendar2024.transition(d)) warnings.add("DST_WEEK: "+d);
            }
            var c=totals.getOrDefault(w,new Counter());if(c.kept<minTotal) warnings.add("LOW_WEEK_TOTAL");
            weeks.add(new Week(w,c.counts(),c.sources(imports),!warnings.contains("SOURCE_MONTH_MISSING")&&c.kept>=minTotal,warnings));
        }
        var c=sum(totals,from,to);return new Period(from,to,c.counts(),c.sources(imports),weeks);
    }
}
