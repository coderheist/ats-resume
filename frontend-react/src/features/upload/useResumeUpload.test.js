import { renderHook, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useResumeUpload } from "./useResumeUpload";
import { apiPostFile } from "../../lib/api";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual("../../lib/api");
  return { ...actual, apiPostFile: vi.fn() };
});

function makeFile(name, size, type = "application/pdf") {
  const file = new File([new Uint8Array(Math.max(size, 1))], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("useResumeUpload", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("rejects a file that isn't .pdf or .docx without ever calling the API", async () => {
    const { result } = renderHook(() => useResumeUpload());
    await act(async () => {
      await result.current.upload(makeFile("resume.txt", 1000));
    });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toMatch(/isn't a \.pdf or \.docx/);
    expect(apiPostFile).not.toHaveBeenCalled();
  });

  it("rejects a file over 10MB without calling the API", async () => {
    const { result } = renderHook(() => useResumeUpload());
    await act(async () => {
      await result.current.upload(makeFile("resume.pdf", 11 * 1024 * 1024));
    });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toMatch(/too large/);
    expect(apiPostFile).not.toHaveBeenCalled();
  });

  it("rejects an empty file", async () => {
    const { result } = renderHook(() => useResumeUpload());
    await act(async () => {
      await result.current.upload(makeFile("resume.pdf", 0));
    });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toMatch(/empty/);
  });

  it("accepts a valid .pdf and stores the parsed result", async () => {
    apiPostFile.mockResolvedValue({ resume: { basics: { name: "Jordan Alvarez" } }, parse_method: "heuristic", warnings: [] });
    const { result } = renderHook(() => useResumeUpload());
    await act(async () => {
      await result.current.upload(makeFile("resume.pdf", 1000));
    });
    expect(result.current.status).toBe("success");
    expect(result.current.result.resume.basics.name).toBe("Jordan Alvarez");
    expect(result.current.fileName).toBe("resume.pdf");
  });

  it("accepts a valid .docx", async () => {
    apiPostFile.mockResolvedValue({ resume: { basics: { name: "Jordan Alvarez" } }, parse_method: "heuristic", warnings: [] });
    const { result } = renderHook(() => useResumeUpload());
    await act(async () => {
      await result.current.upload(makeFile("resume.docx", 1000, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"));
    });
    expect(result.current.status).toBe("success");
  });

  it("treats an empty parsed resume (e.g. scanned PDF) as an error, not a silent success", async () => {
    apiPostFile.mockResolvedValue({ resume: {}, parse_method: "heuristic", warnings: [] });
    const { result } = renderHook(() => useResumeUpload());
    await act(async () => {
      await result.current.upload(makeFile("resume.pdf", 1000));
    });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toMatch(/no text could be extracted/i);
  });

  it("surfaces a real API error", async () => {
    apiPostFile.mockRejectedValue(new Error("413 Payload Too Large"));
    const { result } = renderHook(() => useResumeUpload());
    await act(async () => {
      await result.current.upload(makeFile("resume.pdf", 1000));
    });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("413 Payload Too Large");
  });

  it("reset clears everything back to idle", async () => {
    apiPostFile.mockResolvedValue({ resume: { basics: { name: "Jordan Alvarez" } }, parse_method: "heuristic", warnings: [] });
    const { result } = renderHook(() => useResumeUpload());
    await act(async () => {
      await result.current.upload(makeFile("resume.pdf", 1000));
    });
    expect(result.current.status).toBe("success");
    act(() => result.current.reset());
    expect(result.current.status).toBe("idle");
    expect(result.current.result).toBeNull();
    expect(result.current.fileName).toBeNull();
  });
});
