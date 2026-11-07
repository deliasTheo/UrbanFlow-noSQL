package fr.urbanflow.changes;

import java.time.LocalDate;
import java.util.List;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/flow-changes")
public class ChangeController {
    private final ChangeService service;

    public ChangeController(ChangeService service) {
        this.service = service;
    }

    @GetMapping
    public ChangeService.Response compare(@RequestParam(required = false) List<Integer> zoneIds,
            @RequestParam(required = false) String borough,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate referenceFrom,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate referenceTo,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate baselineFrom,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate baselineTo,
            @RequestParam(defaultValue = "20") int minTrips,
            @RequestParam(defaultValue = "20") int minBaselineTrips,
            @RequestParam(defaultValue = "100") int minTotalTrips,
            @RequestParam(defaultValue = "3") int minBaselineWeeks,
            @RequestParam(defaultValue = "0.001") double minShareChange,
            @RequestParam(defaultValue = "2") double minVariationRatio,
            @RequestParam(defaultValue = "10") int limit) {
        return service.compare(zoneIds, borough, from, to, referenceFrom, referenceTo, baselineFrom, baselineTo,
                minTrips, minBaselineTrips, minTotalTrips, minBaselineWeeks, minShareChange, minVariationRatio, limit);
    }
}
