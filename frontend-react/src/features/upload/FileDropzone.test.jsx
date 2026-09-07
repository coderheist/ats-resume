import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FileDropzone } from "./FileDropzone";

function makeFile(name, type = "application/pdf") {
  return new File(["content"], name, { type });
}

describe("FileDropzone", () => {
  it("shows the idle state by default", () => {
    render(<FileDropzone status="idle" error={null} fileName={null} onFileSelected={() => {}} onReset={() => {}} />);
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
    expect(screen.getByText(/\.pdf or \.docx only/i)).toBeInTheDocument();
  });

  it("shows the uploading state", () => {
    render(<FileDropzone status="uploading" error={null} fileName={null} onFileSelected={() => {}} onReset={() => {}} />);
    expect(screen.getByText(/parsing your resume/i)).toBeInTheDocument();
  });

  it("shows the done state with the filename and a reset option", () => {
    const onReset = vi.fn();
    render(<FileDropzone status="success" error={null} fileName="resume.pdf" onFileSelected={() => {}} onReset={onReset} />);
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Use a different file"));
    expect(onReset).toHaveBeenCalledOnce();
  });

  it("shows an error message when present", () => {
    render(<FileDropzone status="error" error="Something went wrong." fileName={null} onFileSelected={() => {}} onReset={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong.");
  });

  it("calls onFileSelected when a file is dropped", () => {
    const onFileSelected = vi.fn();
    render(<FileDropzone status="idle" error={null} fileName={null} onFileSelected={onFileSelected} onReset={() => {}} />);
    const file = makeFile("resume.pdf");
    const dropzone = screen.getByRole("button", { name: /upload resume/i });
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });
    expect(onFileSelected).toHaveBeenCalledWith(file);
  });

  it("calls onFileSelected when a file is chosen via the hidden input", () => {
    const onFileSelected = vi.fn();
    render(<FileDropzone status="idle" error={null} fileName={null} onFileSelected={onFileSelected} onReset={() => {}} />);
    const file = makeFile("resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    const input = screen.getByTestId("file-input");
    fireEvent.change(input, { target: { files: [file] } });
    expect(onFileSelected).toHaveBeenCalledWith(file);
  });

  it("is keyboard accessible -- Enter triggers browse when idle", () => {
    render(<FileDropzone status="idle" error={null} fileName={null} onFileSelected={() => {}} onReset={() => {}} />);
    const dropzone = screen.getByRole("button", { name: /upload resume/i });
    expect(dropzone).toHaveAttribute("tabIndex", "0");
  });

  it("is not focusable while busy or done", () => {
    const { rerender } = render(<FileDropzone status="uploading" error={null} fileName={null} onFileSelected={() => {}} onReset={() => {}} />);
    expect(screen.getByRole("button", { name: /upload resume/i })).toHaveAttribute("tabIndex", "-1");

    rerender(<FileDropzone status="success" error={null} fileName="resume.pdf" onFileSelected={() => {}} onReset={() => {}} />);
    expect(screen.getByRole("button", { name: /upload resume/i })).toHaveAttribute("tabIndex", "-1");
  });
});
