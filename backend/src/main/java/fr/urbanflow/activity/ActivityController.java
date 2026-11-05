package fr.urbanflow.activity;

import java.time.LocalDate;
import java.util.List;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class ActivityController {
    private final ActivityService service;

    public ActivityController(ActivityService service) { this.service = service; }

    @GetMapping("/zones")
    public List<ActivityService.Zone> zones() { return service.zones(); }

    @GetMapping("/activity")
    public ActivityService.Activity activity(@RequestParam int zoneId, @RequestParam Direction direction,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to) {
        return service.activity(zoneId, direction, from, to);
    }
}
