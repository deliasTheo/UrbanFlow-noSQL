package fr.urbanflow.trips;

import java.time.LocalDate;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/trips")
public class TripController {
    private final TripService service;

    public TripController(TripService service) {
        this.service = service;
    }

    @GetMapping
    public TripService.Response trips(@RequestParam(required = false) Integer pickupZoneId,
            @RequestParam(required = false) Integer dropoffZoneId,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
            @RequestParam(defaultValue = "pickup") String time,
            @RequestParam(defaultValue = "0") int startHour,
            @RequestParam(defaultValue = "24") int endHour,
            @RequestParam(defaultValue = "activity") String profile,
            @RequestParam(defaultValue = "all") String status,
            @RequestParam(defaultValue = "0") int offset,
            @RequestParam(defaultValue = "100") int limit) {
        return service.trips(pickupZoneId, dropoffZoneId, time, from, to, startHour, endHour, profile, status, offset, limit);
    }
}
