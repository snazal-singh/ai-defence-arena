"""
Simplified text extraction module for various document formats with page tracking.

This module provides unified text extraction with automatic file type detection
and consistent output formatting across all supported file types.
"""

import asyncio
import logging
import mimetypes
import os
import re
import unicodedata
from typing import Dict, List, Tuple, Any

# Third-party imports
import fitz  # PyMuPDF
from docx import Document as DocxDocument
from langchain.schema import Document
from openpyxl import load_workbook
from pptx import Presentation
from werkzeug.datastructures import FileStorage

# Namespace URI used by python-docx XML elements
_DOCX_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

# Configure logging
logger = logging.getLogger(__name__)

def _table_rows_to_markdown(rows: List[List]) -> str:
    """Convert a list-of-lists table to a markdown table string."""
    if not rows:
        return ""

    # Normalise all cells to strings and escape pipe characters
    str_rows = [
        [str(cell or "").strip().replace("\n", " ").replace("|", "\\|") for cell in row]
        for row in rows
    ]

    # Pad rows to equal column count
    max_cols = max((len(r) for r in str_rows), default=0)
    if max_cols == 0:
        return ""
    str_rows = [r + [""] * (max_cols - len(r)) for r in str_rows]

    header = "| " + " | ".join(str_rows[0]) + " |"
    separator = "| " + " | ".join(["---"] * max_cols) + " |"
    body = ["| " + " | ".join(r) + " |" for r in str_rows[1:]]
    return "\n".join([header, separator] + body)


def _make_table_id(filename: str, page: int, table_index: int) -> str:
    """Create a stable, unique identifier for a table chunk."""
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
    return f"{safe}_p{page}_t{table_index}"


def clean_filename(filename: str) -> str:
    """Clean filename by removing temporary path prefixes"""
    if not filename:
        return filename
    
    # Handle both Windows and Unix paths
    if '\\' in filename:
        filename = filename.split('\\')[-1]
    if '/' in filename:
        filename = filename.split('/')[-1]
    
    return filename

def clean_text(text: str) -> str:
    """Apply universal text cleaning across all file types"""
    if not text:
        return text
    
    # Normalize Unicode characters
    text = unicodedata.normalize("NFKC", text)
    
    # Replace common problematic characters
    replacements = {
        "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
        """: '"', """: '"', "'": "'", "'": "'", "′": "'",
        "‒": "-", "–": "-", "—": "-", "―": "-",
        "…": "...", "•": "*", "°": " degrees ",
        "©": "(c)", "®": "(R)", "™": "(TM)"
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # Clean control characters while preserving whitespace
    text = "".join(
        char for char in text
        if unicodedata.category(char)[0] != "C" or char in "\n\t "
    )
    
    # Clean up spacing
    text = re.sub(r"[ \t]+", " ", text)  # Consolidate horizontal whitespace
    text = re.sub(r" +\n", "\n", text)  # Remove spaces before newlines
    text = re.sub(r"\n +", "\n", text)  # Remove spaces after newlines
    text = re.sub(r"\n{3,}", "\n\n", text)  # Max two consecutive newlines
    text = re.sub(r"^\s+", "", text)  # Remove leading whitespace
    text = re.sub(r"\s+$", "", text)  # Remove trailing whitespace
    
    # Clean up punctuation spacing
    text = re.sub(r"\s+([.,;:!?)])", r"\1", text)
    text = re.sub(r"(\()\s+", r"\1", text)
    
    # Remove zero-width characters
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u200e\u200f]", "", text)
    
    # Fix hyphenation at line breaks
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    
    return text.strip()

def detect_file_type(file_path: str, filename: str = None) -> str:
    """Detect file type using MIME types and extensions"""
    # Try MIME type detection first
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type
    
    # Fallback to extension
    ext = os.path.splitext(filename or file_path)[1].lower()
    
    ext_mime_map = {
        ".txt": "text/plain",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
    
    return ext_mime_map.get(ext, "text/plain")

async def extract_txt(file_path: str, filename: str) -> List[Document]:
    """Extract text from plain text files - treat as single page"""
    def _read_file():
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()
    
    content = await asyncio.get_event_loop().run_in_executor(None, _read_file)
    cleaned_content = clean_text(content)
    
    if not cleaned_content.strip():
        return []
    
    # Create a single Document for the text file
    doc = Document(
        page_content=cleaned_content,
        metadata={
            "source": filename,
            "page": 0,
            "content_type": "text",
        }
    )
    
    return [doc]

async def extract_pdf(file_path: str, filename: str) -> List[Document]:
    """Extract text from PDF files.

    Produces one *text* Document per page plus one *table* Document per
    detected table (requires PyMuPDF >= 1.23).  Table Documents carry
    ``content_type="table"`` and a stable ``table_id`` so they can be
    retrieved as a whole unit later.
    """
    def _extract():
        pdf = fitz.open(file_path)
        try:
            result = []
            for page_num, page in enumerate(pdf):
                base_meta = {
                    "source": filename,
                    "page": page_num,
                }

                # --- table extraction (PyMuPDF >= 1.23) ---
                try:
                    finder = page.find_tables()
                    for t_idx, table in enumerate(finder.tables):
                        rows = table.extract()
                        md = _table_rows_to_markdown(rows)
                        if md:
                            result.append(Document(
                                page_content=md,
                                metadata={
                                    **base_meta,
                                    "content_type": "table",
                                    "table_id": _make_table_id(filename, page_num, t_idx),
                                    "table_index": t_idx,
                                },
                            ))
                except AttributeError:
                    pass  # find_tables not available in this PyMuPDF version

                # --- full page text ---
                text = page.get_text()
                if text.strip():
                    result.append({
                        "content": text,
                        "page_number": page_num,
                    })
            return result
        finally:
            pdf.close()

    raw = await asyncio.get_event_loop().run_in_executor(None, _extract)

    documents = []
    for item in raw:
        if isinstance(item, Document):
            # Already a table Document
            documents.append(item)
        else:
            cleaned = clean_text(item["content"])
            if cleaned.strip():
                documents.append(Document(
                    page_content=cleaned,
                    metadata={
                        "source": filename,
                        "page": item["page_number"],
                        "content_type": "text",
                    },
                ))

    return documents

def _docx_paragraph_in_table(paragraph) -> bool:
    """Return True if the paragraph element lives inside a table cell."""
    parent = paragraph._element.getparent()
    while parent is not None:
        local = parent.tag.split("}")[-1] if "}" in parent.tag else parent.tag
        if local == "tbl":
            return True
        parent = parent.getparent()
    return False


def _docx_table_to_markdown(table) -> str:
    """Convert a python-docx Table to a markdown string."""
    rows = [
        [cell.text.strip().replace("\n", " ") for cell in row.cells]
        for row in table.rows
    ]
    return _table_rows_to_markdown(rows)


def _docx_table_page_map(doc) -> dict:
    """Return {table_index: page_number} by walking the body XML in order."""
    current_page = 0
    table_index = 0
    mapping: dict = {}
    ns_uri = f"{{{_DOCX_NS}}}"

    for child in doc.element.body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "tbl":
            mapping[table_index] = current_page
            table_index += 1
        elif tag == "p":
            # Detect explicit page breaks
            for br in child.iter(f"{ns_uri}br"):
                if br.get(f"{ns_uri}type") == "page":
                    current_page += 1
                    break
    return mapping


async def extract_docx(file_path: str, filename: str) -> List[Document]:
    """Extract content from DOCX files.

    Produces text Documents (one per logical page / page-break region) plus
    one table Document per table, with ``content_type`` and ``table_id``
    metadata.  Table-cell paragraphs are skipped in the text pass so content
    is not duplicated.
    """
    def _extract():
        doc = DocxDocument(file_path)
        result: List[Document] = []

        # Build table → page mapping before text pass
        table_page_map = _docx_table_page_map(doc)

        # --- text pass (skip paragraphs inside tables) ---
        current_page_content: List[str] = []
        current_page = 0

        for paragraph in doc.paragraphs:
            if _docx_paragraph_in_table(paragraph):
                continue

            style = paragraph.style.name if paragraph.style else "Normal"
            text = paragraph.text.strip()

            # Page break → flush current page
            if paragraph._element.xpath('.//w:br[@w:type="page"]'):
                if current_page_content:
                    result.append({
                        "content": "\n\n".join(current_page_content),
                        "page_number": current_page,
                    })
                    current_page_content = []
                    current_page += 1
                continue

            if not text:
                continue

            if "Heading" in style:
                level = style[-1] if style[-1].isdigit() else "1"
                current_page_content.append(f"\n{'#' * int(level)} {text}\n")
            else:
                formatted: List[str] = []
                for run in paragraph.runs:
                    if run.bold:
                        formatted.append(f"**{run.text}**")
                    elif run.italic:
                        formatted.append(f"*{run.text}*")
                    else:
                        formatted.append(run.text)
                current_page_content.append("".join(formatted))

        if current_page_content:
            result.append({
                "content": "\n\n".join(current_page_content),
                "page_number": current_page,
            })

        # --- table pass ---
        for t_idx, table in enumerate(doc.tables):
            md = _docx_table_to_markdown(table)
            if md:
                page_num = table_page_map.get(t_idx, 0)
                result.append(Document(
                    page_content=md,
                    metadata={
                        "source": filename,
                        "page": page_num,
                        "content_type": "table",
                        "table_id": _make_table_id(filename, page_num, t_idx),
                        "table_index": t_idx,
                    },
                ))

        return result

    raw = await asyncio.get_event_loop().run_in_executor(None, _extract)

    documents: List[Document] = []
    for item in raw:
        if isinstance(item, Document):
            documents.append(item)
        else:
            cleaned = clean_text(item["content"])
            if cleaned.strip():
                documents.append(Document(
                    page_content=cleaned,
                    metadata={
                        "source": filename,
                        "page": item["page_number"],
                        "content_type": "text",
                    },
                ))

    return documents

async def extract_pptx(file_path: str, filename: str) -> List[Document]:
    """Extract content from PPTX files — one text Document per slide plus one
    table Document per table shape, tagged with ``content_type`` metadata.
    """
    def _extract():
        prs = Presentation(file_path)
        result = []

        for slide_num, slide in enumerate(prs.slides):
            base_meta = {
                "source": filename,
                "page": slide_num,
            }

            text_parts = [f"\n# Slide {slide_num + 1}\n"]
            table_index = 0

            # Title
            if slide.shapes.title and slide.shapes.title.text.strip():
                text_parts.append(f"## {slide.shapes.title.text.strip()}\n")

            for shape in slide.shapes:
                # Table shapes
                if shape.has_table:
                    rows = [
                        [cell.text.strip().replace("\n", " ") for cell in row.cells]
                        for row in shape.table.rows
                    ]
                    md = _table_rows_to_markdown(rows)
                    if md:
                        result.append(Document(
                            page_content=md,
                            metadata={
                                **base_meta,
                                "content_type": "table",
                                "table_id": _make_table_id(filename, slide_num, table_index),
                                "table_index": table_index,
                            },
                        ))
                    table_index += 1
                    continue

                # Text shapes (skip title — already added)
                if shape == slide.shapes.title:
                    continue
                if hasattr(shape, "text") and shape.text.strip():
                    text_parts.append(shape.text.strip())

            result.append({
                "content": "\n\n".join(text_parts),
                "page_number": slide_num,
            })

        return result

    raw = await asyncio.get_event_loop().run_in_executor(None, _extract)

    documents: List[Document] = []
    for item in raw:
        if isinstance(item, Document):
            documents.append(item)
        else:
            cleaned = clean_text(item["content"])
            if cleaned.strip():
                documents.append(Document(
                    page_content=cleaned,
                    metadata={
                        "source": filename,
                        "page": item["page_number"],
                        "content_type": "text",
                    },
                ))

    return documents

async def extract_xlsx(file_path: str, filename: str) -> List[Document]:
    """Extract content from XLSX files - one Document per sheet"""
    def _extract():
        wb = load_workbook(file_path, data_only=True)
        sheets_data = []
        
        for sheet_index, sheet_name in enumerate(wb.sheetnames):
            ws = wb[sheet_name]
            content = []
            content.append(f"\n# Sheet: {sheet_name}\n")
            
            max_row = min(ws.max_row or 1, 1000)
            max_col = min(ws.max_column or 1, 50)
            
            if max_row <= 1:
                content.append("(Empty sheet)")
            else:
                # Create table
                headers = []
                for col in range(1, max_col + 1):
                    cell_value = ws.cell(row=1, column=col).value
                    headers.append(str(cell_value) if cell_value is not None else "")
                
                content.append("| " + " | ".join(headers) + " |")
                content.append("| " + " | ".join(["---"] * len(headers)) + " |")
                
                # Add data rows
                for row in range(2, max_row + 1):
                    row_data = []
                    for col in range(1, max_col + 1):
                        cell_value = ws.cell(row=row, column=col).value
                        row_data.append(str(cell_value) if cell_value is not None else "")
                    content.append("| " + " | ".join(row_data) + " |")
            
            sheets_data.append({
                "content": "\n".join(content),
                "page_number": sheet_index  # Sheet index as page number
            })
        
        return sheets_data
    
    sheets_data = await asyncio.get_event_loop().run_in_executor(None, _extract)
    
    documents = []
    for sheet_data in sheets_data:
        cleaned_content = clean_text(sheet_data["content"])
        if cleaned_content.strip():
            doc = Document(
                page_content=cleaned_content,
                metadata={
                    "source": filename,
                    "page": sheet_data["page_number"],
                    "content_type": "text",
                }
            )
            documents.append(doc)
    
    return documents

async def extract_content_from_file(user_session: str, filename: str = None) -> Dict[str, Any]:
    """
    Extract content from any supported file type with page tracking
    
    Args:
        file_path: Path to the file
        filename: Original filename
        
    Returns:
        Dictionary with extracted documents and metadata
    """
    # clean_name = clean_filename(filename or os.path.basename(file_path))
    # logger.info(f'clean name: {clean_name}, file path: {file_path} ---------------------')
    # file_path = 'files/carnot_test1758108569065sfspo89r6/What_is_politics-1.pdf'

    clean_name = clean_filename(filename)
    file_path = f'files/{user_session}/{clean_name}'
    logger.info(f'******************file path: {file_path}*********************')
    
    # Validate file
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        logger.info(f'file not saved correctly ++++++++++++++++++')
        return {
            "documents": [],
            "metadata": {"filename": clean_name, "error": "File not found or empty"},
            "success": False
        }
    logger.info(f'file saved correctly ===================')
    
    # Detect file type
    file_type = detect_file_type(file_path, filename)
    
    try:
        # Extract based on file type
        if file_type == "text/plain":
            documents = await extract_txt(file_path, clean_name)
        elif file_type == "application/pdf":
            documents = await extract_pdf(file_path, clean_name)
        elif file_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            documents = await extract_docx(file_path, clean_name)
        elif file_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            documents = await extract_pptx(file_path, clean_name)
        elif file_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            documents = await extract_xlsx(file_path, clean_name)
        else:
            # Fallback to text
            documents = await extract_txt(file_path, clean_name)
        
        if not documents:
            return {
                "documents": [],
                "metadata": {"filename": clean_name, "error": "No content extracted"},
                "success": False
            }
        
        total_content_length = sum(len(doc.page_content) for doc in documents)
        
        return {
            "documents": documents,
            "metadata": {
                "filename": clean_name,
                "file_type": file_type,
                "total_pages": len(documents),
                "content_length": total_content_length
            },
            "success": True
        }
        
    except Exception as e:
        logger.error(f"Error extracting content from {clean_name}: {e}")
        return {
            "documents": [],
            "metadata": {"filename": clean_name, "error": str(e)},
            "success": False
        }

def get_text_from_files(files: List[FileStorage], user_session: str) -> Tuple[List[Document], List[Dict[str, Any]]]:
    """
    Extract text from multiple files (main interface for document_service.py)
    
    Args:
        files: List of file objects
        
    Returns:
        Tuple of (list of Document objects, list of file_info dictionaries)
    """
    async def _async_extract():
        all_documents = []
        file_infos = []
        
        for file in files:
            temp_path = None
            try:
                # Create temporary file
                # with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
                #     file.save(temp_file.name)
                #     temp_path = temp_file.name
                
                # Extract content
                result = await extract_content_from_file(user_session, file.filename)
                
                if result["success"] and result["documents"]:
                    logger.info(f"Successfully extracted {len(result['documents'])} pages from {file.filename}")
                    # Add all documents from this file
                    all_documents.extend(result["documents"])
                
                # File info for tracking
                file_info = {
                    "filename": file.filename,
                    "success": result["success"],
                    "page_count": len(result["documents"]) if result["documents"] else 0,
                    "content_length": result["metadata"].get("content_length", 0)
                }
                
                if not result["success"]:
                    file_info["error"] = result["metadata"].get("error", "Unknown error")
                
                file_infos.append(file_info)
                
            except Exception as e:
                logger.error(f"Error processing file {file.filename}: {e}")
                file_infos.append({
                    "filename": file.filename,
                    "success": False,
                    "error": str(e)
                })
            finally:
                # Clean up temporary file
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
        
        return all_documents, file_infos
    
    # Run async function synchronously
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_async_extract())
    finally:
        loop.close()

# Standalone usage support
async def extract_from_path(file_path: str) -> Dict[str, Any]:
    """Extract content from a file path (for standalone usage)"""
    if not os.path.exists(file_path):
        return {"success": False, "error": f"File not found: {file_path}"}
    
    return await extract_content_from_file(file_path)

def main():
    """Main function for standalone usage"""
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="Extract text from documents")
    parser.add_argument("--file", "-f", help="Path to file")
    parser.add_argument("--output", "-o", help="Output file path")
    
    args = parser.parse_args()
    
    if not args.file:
        parser.print_help()
        sys.exit(1)
    
    async def _extract():
        result = await extract_from_path(args.file)
        
        if result["success"]:
            documents = result["documents"]
            print(f"Successfully extracted text from: {result['metadata']['filename']}")
            print(f"Total pages: {len(documents)}")
            print(f"Total content length: {result['metadata']['content_length']} characters")
            print("-" * 50)
            
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    for doc in documents:
                        f.write(f"=== Page {doc.metadata['page'] + 1} ===\n")
                        f.write(doc.page_content)
                        f.write(f"\n\n")
                print(f"Content saved to: {args.output}")
            else:
                print("Extracted content (first page preview):")
                if documents:
                    content = documents[0].page_content
                    print(content[:1000] + "..." if len(content) > 1000 else content)
        else:
            print(f"Error: {result['metadata']['error']}")
            sys.exit(1)
    
    asyncio.run(_extract())

if __name__ == "__main__":
    main()