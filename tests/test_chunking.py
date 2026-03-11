from app.services.chunking import MarkdownChunker


def test_heading_aware_chunking_keeps_headers():
    markdown = "# Intro\nFirst block.\n\n## Auth\n" + ("token " * 220) + "\n\n## Errors\n" + ("error " * 220)
    chunker = MarkdownChunker(target_chars=180, overlap_chars=24)

    chunks = chunker.split(markdown)

    assert len(chunks) >= 3
    assert chunks[0].text.startswith("# Intro")
    assert any("## Auth" in chunk.text for chunk in chunks)
    assert any("## Errors" in chunk.text for chunk in chunks)

