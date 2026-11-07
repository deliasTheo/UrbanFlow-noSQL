package fr.urbanflow.imports;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import org.bson.Document;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.query.Query;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

// L'import reste écrit en Python (urbanflow/ingest.py). L'API le lance et renvoie
// ce qu'il a affiché, pour que les six services passent par la même interface.
@Service
public class ImportService {
    private final MongoTemplate mongo;
    private final String mongoUri;
    private final String database;
    private boolean running = false;

    public ImportService(MongoTemplate mongo,
            @Value("${spring.data.mongodb.uri}") String mongoUri,
            @Value("${spring.data.mongodb.database}") String database) {
        this.mongo = mongo;
        this.mongoUri = mongoUri;
        this.database = database;
    }

    public record ImportInfo(String fileId, String fileName, String month, String status,
            Number numRows, Number inserted, Number alreadyPresent, Number seconds) {}

    public record ImportResult(int exitCode, List<String> output) {}

    public List<ImportInfo> list() {
        var query = new Query().with(Sort.by("started_at"));
        return mongo.find(query, Document.class, "imports").stream().map(ImportService::info).toList();
    }

    private static ImportInfo info(Document d) {
        Document summary = d.get("summary", new Document());
        return new ImportInfo(d.getString("_id"), d.getString("file_name"), d.getString("file_month"),
                d.getString("status"), d.get("num_rows", Number.class), summary.get("inserted", Number.class),
                summary.get("already_present", Number.class), summary.get("seconds", Number.class));
    }

    public ImportResult importFile(String month, String file) {
        if (month == null && file == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Indiquer month (AAAA-MM) ou file (chemin d'un Parquet).");
        }
        if (!start()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Un import est déjà en cours.");
        }
        try {
            return runIngest(month, file);
        } catch (IOException e) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Impossible de lancer l'import : " + e.getMessage());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Import interrompu.");
        } finally {
            finish();
        }
    }

    private synchronized boolean start() {
        if (running) {
            return false;
        }
        running = true;
        return true;
    }

    private synchronized void finish() {
        running = false;
    }

    private ImportResult runIngest(String month, String file) throws IOException, InterruptedException {
        Path root = projectRoot();
        var command = new ArrayList<String>();
        command.add(pythonPath(root));
        command.addAll(List.of("-m", "urbanflow.ingest", "--database", database));
        if (month != null) {
            command.addAll(List.of("--month", month));
        }
        if (file != null) {
            command.addAll(List.of("--file", file));
        }

        var builder = new ProcessBuilder(command).directory(root.toFile()).redirectErrorStream(true);
        builder.environment().put("MONGODB_URI", mongoUri);
        builder.environment().put("PYTHONIOENCODING", "utf-8");
        Process process = builder.start();

        String text = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        int exitCode = process.waitFor();
        List<String> lines = text.lines().toList();
        if (exitCode != 0) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                    "Import en échec : " + lines.get(lines.size() - 1));
        }
        return new ImportResult(exitCode, lines);
    }

    // L'API peut être lancée depuis la racine du dépôt ou depuis backend/.
    private static Path projectRoot() {
        Path here = Path.of("").toAbsolutePath();
        return Files.exists(here.resolve("urbanflow/ingest.py")) ? here : here.getParent();
    }

    private static String pythonPath(Path root) {
        Path windows = root.resolve(".venv/Scripts/python.exe");
        Path linux = root.resolve(".venv/bin/python");
        if (Files.exists(windows)) {
            return windows.toString();
        }
        return Files.exists(linux) ? linux.toString() : "python";
    }
}
