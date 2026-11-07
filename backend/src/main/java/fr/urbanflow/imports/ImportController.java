package fr.urbanflow.imports;

import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

// Service F6 : importer un fichier et voir ce qui est déjà dans la base.
@RestController
@RequestMapping("/api/imports")
public class ImportController {
    private final ImportService service;

    public ImportController(ImportService service) {
        this.service = service;
    }

    @GetMapping
    public List<ImportService.ImportInfo> list() {
        return service.list();
    }

    @PostMapping
    public ImportService.ImportResult importFile(@RequestParam(required = false) String month,
            @RequestParam(required = false) String file) {
        return service.importFile(month, file);
    }
}
