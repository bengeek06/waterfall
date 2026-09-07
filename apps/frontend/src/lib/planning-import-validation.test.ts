import { describe, expect, it } from "vitest";

import { MAX_IMPORT_FILE_SIZE, validateImportFile } from "./planning-import-validation";

function fileWithSize(name: string, size: number, type = "application/xml"): File {
  const file = new File(["content"], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("validateImportFile", () => {
  it("accepts a valid .xml file", () => {
    const file = fileWithSize("planning.xml", 1024);
    expect(validateImportFile(file)).toBeNull();
  });

  it("accepts a .xml extension regardless of case", () => {
    const file = fileWithSize("planning.XML", 1024);
    expect(validateImportFile(file)).toBeNull();
  });

  it("rejects a file with a different extension", () => {
    const file = fileWithSize("planning.docx", 1024);
    expect(validateImportFile(file)).toBe("Seuls les fichiers .xml sont acceptés.");
  });

  it("rejects a .xml file larger than 25 MiB", () => {
    const file = fileWithSize("planning.xml", MAX_IMPORT_FILE_SIZE + 1);
    expect(validateImportFile(file)).toBe("Le fichier XML ne doit pas dépasser 25 MiB.");
  });

  it("accepts a .xml file exactly at the 25 MiB limit", () => {
    const file = fileWithSize("planning.xml", MAX_IMPORT_FILE_SIZE);
    expect(validateImportFile(file)).toBeNull();
  });
});
