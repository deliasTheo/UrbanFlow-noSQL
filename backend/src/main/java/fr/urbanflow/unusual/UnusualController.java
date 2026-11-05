package fr.urbanflow.unusual;

import java.time.LocalDate;
import java.util.List;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/unusual-activity")
public class UnusualController {
    private final UnusualService service;
    public UnusualController(UnusualService service) { this.service=service; }
    @GetMapping
    public UnusualService.Response investigate(@RequestParam(required=false) List<Integer> zoneIds,
        @RequestParam(required=false) String borough,@RequestParam(defaultValue="pickup") String direction,
        @RequestParam @DateTimeFormat(iso=DateTimeFormat.ISO.DATE) LocalDate from,
        @RequestParam @DateTimeFormat(iso=DateTimeFormat.ISO.DATE) LocalDate to,
        @RequestParam @DateTimeFormat(iso=DateTimeFormat.ISO.DATE) LocalDate referenceFrom,
        @RequestParam @DateTimeFormat(iso=DateTimeFormat.ISO.DATE) LocalDate referenceTo,
        @RequestParam(defaultValue="0") int startHour,@RequestParam(defaultValue="24") int endHour,
        @RequestParam(defaultValue="3") int minReferenceDays,@RequestParam(defaultValue="20") int minBaseline,
        @RequestParam(defaultValue="20") int minAbsoluteChange,@RequestParam(defaultValue="0.5") double minRelativeChange,
        @RequestParam(defaultValue="3") double minRobustScore) {
        return service.investigate(zoneIds,borough,direction,from,to,referenceFrom,referenceTo,startHour,endHour,
            minReferenceDays,minBaseline,minAbsoluteChange,minRelativeChange,minRobustScore);
    }
}
