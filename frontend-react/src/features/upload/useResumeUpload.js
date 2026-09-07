import { useCallback, useState } from "react";
import { apiPostFile } from "../../lib/api";

// Matches app/core/parsing/file_extraction.py's SUPPORTED_EXTENSIONS and
// app/api/routes/resume.py's MAX_UPLOAD_BYTES exactly -- client-side
// validation here is a fast-fail UX nicety, not the actual security
// boundary; the backend enforces both independently regardless.
const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];
const MAX_BYTES = 10 * 1024 * 1024;

export function isAcceptedFile(file) {
  const lowerName = file.name.toLowerCase();
  // Extension match only, not MIME type: some browser/OS combinations
  // report an empty or generic MIME type for .docx uploads specifically,
  // which would make a MIME-based check reject a perfectly valid file.
  // The backend's own extension check is the real source of truth either
  // way (file_extraction.py raises UnsupportedFileTypeError itself).
  return ACCEPTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
}

export function useResumeUpload() {
  const [status, setStatus] = useState("idle"); // idle | uploading | success | error
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null); // ResumeParseResponse from the backend
  const [fileName, setFileName] = useState(null);

  const upload = useCallback(async (file) => {
    if (!file) return;

    if (!isAcceptedFile(file)) {
      setStatus("error");
      setError(`"${file.name}" isn't a .pdf or .docx file. Only those two formats are supported.`);
      return;
    }
    if (file.size > MAX_BYTES) {
      setStatus("error");
      setError(`"${file.name}" is too large (max 10 MB).`);
      return;
    }
    if (file.size === 0) {
      setStatus("error");
      setError(`"${file.name}" is empty.`);
      return;
    }

    setStatus("uploading");
    setError(null);
    setFileName(file.name);
    try {
      const response = await apiPostFile("/resume/parse-file", file);
      if (!response.resume || Object.keys(response.resume).length === 0) {
        // A real, expected outcome for a scanned/image-only PDF (see
        // resume.py's own comment on this) -- not a network/API error,
        // but the user still needs to know nothing was extracted.
        setStatus("error");
        setError(
          "No text could be extracted from this file (it may be a scanned image rather than a real text document)."
        );
        return;
      }
      setResult(response);
      setStatus("success");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setError(null);
    setResult(null);
    setFileName(null);
  }, []);

  return { status, error, result, fileName, upload, reset };
}
