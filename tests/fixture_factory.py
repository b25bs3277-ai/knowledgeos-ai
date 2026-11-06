"""Generates small synthetic documents of every supported type (no confidential data)."""
from __future__ import annotations

from pathlib import Path

ML_PAGES = [
    "Supervised learning trains models on labeled examples. Each input has a known target output.",
    "Unsupervised learning finds structure in unlabeled data, for example clustering with k-means.",
    "Reinforcement learning agents learn by trial and error using rewards from an environment.",
]


def make_pdf(pages: list[str]) -> bytes:
    """Minimal valid multi-page PDF with real extractable text (Helvetica)."""
    n = len(pages)
    kids = " ".join(f"{4 + 2*i} 0 R" for i in range(n))
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 11 Tf 50 720 Td ({safe}) Tj ET".encode("latin-1")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2*i} 0 R >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def make_docx(path: Path) -> None:
    import docx

    d = docx.Document()
    d.add_heading("Model Evaluation", level=1)
    d.add_paragraph("Precision measures how many predicted positives are correct.")
    d.add_heading("Recall", level=2)
    d.add_paragraph("Recall measures how many actual positives the model found.")
    t = d.add_table(rows=3, cols=2)
    for r, (a, b) in enumerate([("Metric", "Range"), ("Precision", "0 to 1"), ("Recall", "0 to 1")]):
        t.cell(r, 0).text, t.cell(r, 1).text = a, b
    d.save(str(path))


def make_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Models"
    ws.append(["Model", "Type", "Accuracy"])
    ws.append(["Random Forest", "Ensemble", "0.91"])
    ws.append(["Logistic Regression", "Linear", "0.86"])
    ws2 = wb.create_sheet("Datasets")
    ws2.append(["Dataset", "Rows"])
    ws2.append(["Iris", "150"])
    wb.save(str(path))


def write_all(directory: Path) -> dict[str, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        ".pdf": directory / "ml_basics.pdf",
        ".txt": directory / "notes.txt",
        ".md": directory / "guide.md",
        ".docx": directory / "evaluation.docx",
        ".csv": directory / "students.csv",
        ".xlsx": directory / "models.xlsx",
    }
    files[".pdf"].write_bytes(make_pdf(ML_PAGES))
    files[".txt"].write_text(
        "Gradient descent minimises a loss function by stepping against the gradient.\n\n"
        "The learning rate controls the step size. Too large a rate can diverge.", encoding="utf-8")
    files[".md"].write_text(
        "# Neural Networks\nNeural networks stack layers of weighted sums and activations.\n\n"
        "## Backpropagation\nBackpropagation computes gradients with the chain rule.\n", encoding="utf-8")
    make_docx(files[".docx"])
    files[".csv"].write_text("name,score,grade\nAsha,92,A\nRavi,78,B\nMeera,85,A\n", encoding="utf-8")
    make_xlsx(files[".xlsx"])
    return files

