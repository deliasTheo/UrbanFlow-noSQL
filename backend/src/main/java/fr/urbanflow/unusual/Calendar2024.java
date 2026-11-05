package fr.urbanflow.unusual;

import java.time.*;
import java.util.Map;

public final class Calendar2024 {
    private Calendar2024() {}
    public static final String SOURCE = "https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/#url=2024";
    private static final Map<LocalDate,String> HOLIDAYS = Map.ofEntries(
        Map.entry(LocalDate.of(2024,1,1), "New Year's Day"),
        Map.entry(LocalDate.of(2024,1,15), "Birthday of Martin Luther King, Jr."),
        Map.entry(LocalDate.of(2024,2,19), "Washington's Birthday"),
        Map.entry(LocalDate.of(2024,5,27), "Memorial Day"),
        Map.entry(LocalDate.of(2024,6,19), "Juneteenth National Independence Day"),
        Map.entry(LocalDate.of(2024,7,4), "Independence Day"),
        Map.entry(LocalDate.of(2024,9,2), "Labor Day"),
        Map.entry(LocalDate.of(2024,10,14), "Columbus Day"),
        Map.entry(LocalDate.of(2024,11,11), "Veterans Day"),
        Map.entry(LocalDate.of(2024,11,28), "Thanksgiving Day"),
        Map.entry(LocalDate.of(2024,12,25), "Christmas Day"));
    public static String holiday(LocalDate day) { return HOLIDAYS.get(day); }
    public static boolean transition(LocalDate day) {
        var tz=ZoneId.of("America/New_York");
        return Duration.between(day.atStartOfDay(tz), day.plusDays(1).atStartOfDay(tz)).toHours()!=24;
    }
}
