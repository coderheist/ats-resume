import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useRef, useState } from "react";
import { Check, Upload } from "lucide-react";

const ACCEPT_ATTR = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function FileDropzone({ status, error, fileName, onFileSelected, onReset }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef(null);

  const handleFiles = useCallback(
    (fileList) => {
      const file = fileList?.[0];
      if (file) onFileSelected(file);
    },
    [onFileSelected]
  );

  function handleDrop(e) {
    e.preventDefault();
    setIsDragOver(false);
    handleFiles(e.dataTransfer.files);
  }

  function handleDragOver(e) {
    e.preventDefault();
    setIsDragOver(true);
  }

  function handleDragLeave() {
    setIsDragOver(false);
  }

  function handleBrowseClick() {
    inputRef.current?.click();
  }

  const isBusy = status === "uploading";
  const isDone = status === "success";

  return (
    <div
      className={`dropzone ${isDragOver ? "drag-over" : ""} ${isDone ? "dropzone-done" : ""} ${error ? "dropzone-error" : ""}`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={isDone || isBusy ? undefined : handleBrowseClick}
      role="button"
      tabIndex={isDone || isBusy ? -1 : 0}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !isDone && !isBusy) handleBrowseClick();
      }}
      aria-label="Upload resume, PDF or DOCX only"
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTR}
        className="visually-hidden"
        onChange={(e) => handleFiles(e.target.files)}
        data-testid="file-input"
      />

      <AnimatePresence mode="wait">
        {isBusy && (
          <motion.div key="uploading" className="dropzone-state" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="spinner" aria-hidden="true" />
            <p>Parsing your resume…</p>
          </motion.div>
        )}

        {isDone && (
          <motion.div
            key="done"
            className="dropzone-state"
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="dropzone-check">
              <Check size={20} aria-hidden="true" />
            </div>
            <p>{fileName}</p>
            <button
              type="button"
              className="btn-link"
              onClick={(e) => {
                e.stopPropagation();
                onReset();
              }}
            >
              Use a different file
            </button>
          </motion.div>
        )}

        {!isBusy && !isDone && (
          <motion.div key="idle" className="dropzone-state" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="dropzone-icon" aria-hidden="true">
              <Upload size={26} />
            </div>
            <p>
              <strong>Drop your resume here</strong>, or click to browse
            </p>
            <p className="dropzone-hint">.pdf or .docx only — max 10 MB</p>
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <p className="dropzone-error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
