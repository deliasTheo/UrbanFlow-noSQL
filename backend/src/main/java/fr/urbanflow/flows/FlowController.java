package fr.urbanflow.flows;

import java.time.LocalDate;
import java.util.List;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/flows")
public class FlowController {
    private final FlowService service;

    public FlowController(FlowService service) {
        this.service = service;
    }

    @GetMapping
    public FlowService.Response flows(@RequestParam(required = false) List<Integer> zoneIds,
            @RequestParam(required = false) String borough,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam(defaultValue = "10") int limit,
            @RequestParam(defaultValue = "20") int minTrips,
            @RequestParam(defaultValue = "5") int minWeeklyTrips,
            @RequestParam(defaultValue = "0.75") double regularFraction,
            @RequestParam(defaultValue = "0.5") double peakShare) {
        return service.flows(zoneIds, borough, from, to, limit, minTrips, minWeeklyTrips, regularFraction, peakShare);
    }
}
