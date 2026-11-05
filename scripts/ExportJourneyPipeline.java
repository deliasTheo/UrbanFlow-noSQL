import fr.urbanflow.journeys.JourneyRepository;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.stream.Collectors;
class ExportJourneyPipeline {
    public static void main(String[] a) {
        var stages=JourneyRepository.pipeline(Integer.parseInt(a[0]),Integer.parseInt(a[1]),LocalDate.parse(a[2]),
            LocalDate.parse(a[3]),LocalDate.parse(a[4]),LocalDate.parse(a[5]),Arrays.asList(a[6].split(",")));
        System.out.println(stages.stream().map(d -> d.toJson()).collect(Collectors.joining(",","[","]")));
    }
}
