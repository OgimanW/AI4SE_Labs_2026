"""Loader (deterministic): read files, assign DOC-IDs, chunk."""
from pathlib import Path

from ..loaders import chunk_text, discover_files, load_file
from ..schemas import Chunk, Document
from .common import event


def loader_node(state) -> dict:
    input_dir = Path(state["input_dir"])
    files = discover_files(input_dir)
    width = max(2, len(str(len(files))))
    docs, chunks, skipped = [], [], []
    for i, path in enumerate(files, 1):
        doc_id = f"DOC-{i:0{width}d}"
        rel = path.relative_to(input_dir).as_posix()
        try:
            text, date = load_file(path)
        except Exception as exc:  # noqa: BLE001 - reported, not fatal
            skipped.append(f"{rel}: {exc}")
            continue
        docs.append(Document(doc_id=doc_id, path=rel, text=text, date=date))
        parts = chunk_text(text)
        chunks += [Chunk(chunk_id=f"{doc_id}#{k}", doc_id=doc_id, index=k, total=len(parts),
                         text=p, date=date) for k, p in enumerate(parts, 1)]
    return {"documents": docs, "chunks": chunks,
            "log": [event("loader", documents=len(docs), chunks=len(chunks), skipped=skipped)]}
