from __future__ import annotations

from pathlib import Path


def default_output_md(source: Path, output_dir: Path | None = None) -> Path:
    """Build a collision-resistant markdown path.

    example.docx -> example.docx.md
    notes.PDF    -> notes.pdf.md
    """
    name = f"{source.name}.md" if source.suffix else f"{source.name}.md"
    # normalize double extensions case: keep original suffix lowercased for stability
    if source.suffix:
        name = f"{source.stem}{source.suffix.lower()}.md"
    base = output_dir if output_dir is not None else source.parent
    return (base / name).resolve()
