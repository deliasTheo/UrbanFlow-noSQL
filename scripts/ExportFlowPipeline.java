// Outil de mesure : réutilise le constructeur du pipeline de production.
import fr.urbanflow.flows.FlowRepository;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.stream.Collectors;

class ExportFlowPipeline {
    public static void main(String[] args) {
        var zones = Arrays.stream(args[0].split(",")).map(Integer::valueOf).toList();
        var files = Arrays.asList(args[3].split(","));
        var stages = FlowRepository.pipeline(zones, LocalDate.parse(args[1]), LocalDate.parse(args[2]), files);
        System.out.println(stages.stream().map(d -> d.toJson()).collect(Collectors.joining(",", "[", "]")));
    }
}
