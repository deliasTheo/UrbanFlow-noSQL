package fr.urbanflow;

// Lignes candidates, retenues et exclues : la même preuve dans tous les services.
public record Counts(long raw, long retained, long excluded) {}
