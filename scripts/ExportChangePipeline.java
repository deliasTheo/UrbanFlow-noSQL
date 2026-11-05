import fr.urbanflow.changes.ChangeRepository;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.stream.Collectors;
class ExportChangePipeline {
    public static void main(String[] a) {
        var p=ChangeRepository.pipeline(Arrays.stream(a[0].split(",")).map(Integer::valueOf).toList(),LocalDate.parse(a[1]),LocalDate.parse(a[2]),
            LocalDate.parse(a[3]),LocalDate.parse(a[4]),LocalDate.parse(a[5]),LocalDate.parse(a[6]),Arrays.asList(a[7].split(",")));
        System.out.println(p.stream().map(d -> d.toJson()).collect(Collectors.joining(",","[","]")));
    }
}
