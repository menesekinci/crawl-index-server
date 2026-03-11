from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TextChunk:
    index: int
    text: str
    token_estimate: int


class MarkdownChunker:
    def __init__(self, target_chars: int = 800, overlap_chars: int = 120):
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def split(self, markdown: str) -> list[TextChunk]:
        sections = self._sectionize(markdown)
        chunks: list[str] = []
        buffer = ""
        for section in sections:
            if not buffer:
                buffer = section
                continue
            if len(buffer) + len(section) + 2 <= self.target_chars:
                buffer = f"{buffer}\n\n{section}"
                continue
            chunks.extend(self._fallback_split(buffer))
            buffer = section
        if buffer:
            chunks.extend(self._fallback_split(buffer))
        return [
            TextChunk(index=i, text=chunk, token_estimate=max(1, len(chunk) // 4))
            for i, chunk in enumerate(chunk for chunk in chunks if chunk.strip())
        ]

    def _sectionize(self, markdown: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        for line in markdown.splitlines():
            if line.startswith("#") and current:
                parts.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)
        if current:
            parts.append("\n".join(current).strip())
        return [part for part in parts if part]

    def _fallback_split(self, text: str) -> list[str]:
        if len(text) <= self.target_chars:
            return [text]
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if len(candidate) <= self.target_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
                overlap = current[-self.overlap_chars :] if self.overlap_chars else ""
                current = f"{overlap}\n\n{paragraph}".strip()
            else:
                chunks.extend(self._hard_split(paragraph))
        if current:
            chunks.append(current)
        return chunks

    def _hard_split(self, paragraph: str) -> list[str]:
        parts: list[str] = []
        start = 0
        while start < len(paragraph):
            end = start + self.target_chars
            parts.append(paragraph[start:end].strip())
            start = max(end - self.overlap_chars, start + 1)
        return [part for part in parts if part]

