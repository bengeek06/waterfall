// Shared validation for the MS Project planning import file, used identically by the manual file
// picker and the drag-and-drop zone (planning-import-panel.tsx) so both paths produce the exact
// same error messages for the same input.
export const MAX_IMPORT_FILE_SIZE = 25 * 1024 * 1024;

export function validateImportFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".xml")) {
    return "Seuls les fichiers .xml sont acceptés.";
  }
  if (file.size > MAX_IMPORT_FILE_SIZE) {
    return "Le fichier XML ne doit pas dépasser 25 MiB.";
  }
  return null;
}
