// Réutilise les deux pipelines F3 exacts pour les plans explain.
import fr.urbanflow.unusual.UnusualRepository;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.stream.Collectors;
class ExportUnusualPipelines {
    public static void main(String[] a) {
        var zones=Arrays.stream(a[0].split(",")).map(Integer::valueOf).toList();
        var files=Arrays.asList(a[8].split(","));
        var values=new java.util.ArrayList<String>();
        for (boolean city:new boolean[]{false,true}) {
            var p=UnusualRepository.pipeline(zones,a[1],LocalDate.parse(a[2]),LocalDate.parse(a[3]),
                LocalDate.parse(a[4]),LocalDate.parse(a[5]),Integer.parseInt(a[6]),Integer.parseInt(a[7]),files,city);
            values.add("\""+(city?"city":"selected")+"\":"+p.stream().map(d -> d.toJson()).collect(Collectors.joining(",","[","]")));
        }
        System.out.println(values.stream().collect(Collectors.joining(",","{","}")));
    }
}
