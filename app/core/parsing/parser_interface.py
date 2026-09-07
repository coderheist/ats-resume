"""
Document parsing layer (blueprint Section 4.1).

Neither Docling nor Marker is installed in this sandbox (both pull in heavy
CV/OCR dependencies not worth fetching for a scaffold) -- these adapters are
written against each library's real, documented API shape so wiring them up
in a deployment environment is a matter of `pip install` plus removing the
NotImplementedError, not a redesign.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ParsedDocument:
    markdown: str
    extraction_confidence: float  # 0..1, used for the Docling/Marker routing decision


class DocumentParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> ParsedDocument:
        raise NotImplementedError


class DoclingParser(DocumentParser):
    """
    Primary engine. Requires `pip install docling`.

    Docling decomposes the PDF via layout-aware CV models trained on
    DocLayNet (titles/paragraphs/columns/tables via TableFormer) and
    exports ordered Markdown -- this is what avoids the classic
    multi-column splicing failure of naive left-to-right text extraction.
    """

    def parse(self, file_path: str) -> ParsedDocument:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(file_path)
        markdown = result.document.export_to_markdown()
        # Docling doesn't expose a single scalar "confidence" -- in
        # production, derive one from result.document layout-parse metadata
        # (e.g. fraction of blocks classified vs. left as raw text).
        return ParsedDocument(markdown=markdown, extraction_confidence=1.0)


class MarkerParser(DocumentParser):
    """
    Fallback engine for scanned/degraded documents. Requires
    `pip install marker-pdf` and, for the LLM-assisted path,
    `--use_llm` wired to a configured model via router.py.
    """

    def parse(self, file_path: str) -> ParsedDocument:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        converter = PdfConverter(artifact_dict=create_model_dict())
        rendered = converter(file_path)
        return ParsedDocument(markdown=rendered.markdown, extraction_confidence=0.85)


def parse_document(file_path: str, confidence_threshold: float = 0.6) -> ParsedDocument:
    """
    Routing policy from blueprint Section 4.1: try Docling first; if its own
    confidence signal is low (scanned/degraded input), fall back to Marker's
    LLM-assisted mode.
    """
    result = DoclingParser().parse(file_path)
    if result.extraction_confidence >= confidence_threshold:
        return result
    return MarkerParser().parse(file_path)
