import io
import re

import pdfplumber
import pymupdf


def extract_text(pdf_bytes: bytes) -> str:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def extract_tables(pdf_bytes: bytes) -> list[list[list[str | None]]]:
    tables: list[list[list[str | None]]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables.extend(page.extract_tables())
    return tables


NOISE_PATTERN = re.compile(r"^\s*(발급일|출력일|담당자|담임)\s*[:：].*$", re.MULTILINE)


def strip_noise(text: str) -> str:
    return NOISE_PATTERN.sub("", text)
