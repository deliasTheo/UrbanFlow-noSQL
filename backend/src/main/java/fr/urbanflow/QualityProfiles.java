package fr.urbanflow;

import java.util.List;

// Les mêmes listes que les profils de urbanflow/quality.py : à changer aux deux endroits.
public final class QualityProfiles {
    private QualityProfiles() {}

    public static final List<String> ACTIVITY = List.of("NEGATIVE_AMOUNT", "EXACT_DUPLICATE");
    public static final List<String> FLOWS = List.of("NEGATIVE_AMOUNT", "EXACT_DUPLICATE", "UNKNOWN_ZONE");
    public static final List<String> JOURNEY = List.of("NEGATIVE_AMOUNT", "EXACT_DUPLICATE", "UNKNOWN_ZONE",
            "NON_POSITIVE_DURATION", "EXCESSIVE_DURATION", "ZERO_DISTANCE", "IMPLAUSIBLE_DISTANCE",
            "IMPLAUSIBLE_SPEED", "DST_UNRESOLVED");
}
