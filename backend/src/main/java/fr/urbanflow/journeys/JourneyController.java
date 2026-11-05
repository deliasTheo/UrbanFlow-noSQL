package fr.urbanflow.journeys;

import java.time.LocalDate;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/journeys")
public class JourneyController {
    private final JourneyService service;
    public JourneyController(JourneyService service) { this.service=service; }
    @GetMapping
    public JourneyService.Response compare(@RequestParam int originId,@RequestParam int destinationId,
        @RequestParam @DateTimeFormat(iso=DateTimeFormat.ISO.DATE) LocalDate from,
        @RequestParam @DateTimeFormat(iso=DateTimeFormat.ISO.DATE) LocalDate to,
        @RequestParam @DateTimeFormat(iso=DateTimeFormat.ISO.DATE) LocalDate referenceFrom,
        @RequestParam @DateTimeFormat(iso=DateTimeFormat.ISO.DATE) LocalDate referenceTo,
        @RequestParam(defaultValue="30") int minTrips) {
        return service.compare(originId,destinationId,from,to,referenceFrom,referenceTo,minTrips);
    }
}
