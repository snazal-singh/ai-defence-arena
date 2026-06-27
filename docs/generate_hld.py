"""
Generates CCP_AIChatbot_HighLevelDesign.docx following the C-DOT Architecture Design
template (PM-QM-TPL-SYSA-C01 v01).

Run:  python3 docs/generate_hld.py
Output: docs/CCP_AIChatbot_HLD.docx
"""

import io
import os
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from docx import Document
from docx.shared import Inches, Pt, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_DOCX = os.path.join(OUT_DIR, "CCP_AIChatbot_HLD.docx")

# ── Diagram colour palette (kept for diagram rendering only) ─────────────────
CDOT_LIGHT  = "#d6e4f7"
GREEN_BG    = "#d4edda"
ORANGE_BG   = "#fff3cd"
RED_BG      = "#f8d7da"
GRAY_BG     = "#f0f0f0"


# ═════════════════════════════════════════════════════════════════════════════
# DIAGRAM HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _box(ax, x, y, w, h, label, bg="#d6e4f7", fontsize=8, bold=False,
         radius=0.04, wrap=18):
    rect = FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle=f"round,pad=0.01,rounding_size={radius}",
        facecolor=bg, edgecolor="#333333", linewidth=0.8, zorder=2,
    )
    ax.add_patch(rect)
    wrapped = "\n".join(textwrap.wrap(label, wrap))
    ax.text(x, y, wrapped, ha="center", va="center", fontsize=fontsize,
            fontweight="bold" if bold else "normal",
            zorder=3, multialignment="center")


def _diamond(ax, x, y, w, h, label, bg=ORANGE_BG, fontsize=7.5):
    pts = [(x, y + h / 2), (x + w / 2, y),
           (x, y - h / 2), (x - w / 2, y)]
    diamond = plt.Polygon(pts, closed=True, facecolor=bg,
                          edgecolor="#333333", linewidth=0.8, zorder=2)
    ax.add_patch(diamond)
    ax.text(x, y, label, ha="center", va="center",
            fontsize=fontsize, zorder=3, multialignment="center")


def _arrow(ax, x1, y1, x2, y2, label="", color="#333333"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color=color,
                                lw=0.9, connectionstyle="arc3,rad=0.0"),
                zorder=1)
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mx + 0.02, my, label, fontsize=6.5, color="#555555", zorder=4)


def _png_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


# ─── Diagram 1 : System Architecture ─────────────────────────────────────────

def diagram_system_architecture():
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.set_xlim(0, 11); ax.set_ylim(0, 7)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.set_title("Figure 1: Overall Architecture of the Sachet AI Chatbot Backend",
                 fontsize=10, fontweight="bold", pad=8)

    for y0, y1, lbl, clr in [
        (6.2, 6.9, "Client Layer",       "#e8f4fd"),
        (5.2, 6.1, "API Layer (Flask)",  "#eaf7ea"),
        (3.2, 5.1, "Service Layer",      "#fff9e6"),
        (1.4, 3.1, "Data Layer",         "#fdecea"),
        (0.2, 1.3, "External Services",  "#f3e8ff"),
    ]:
        ax.add_patch(plt.Rectangle((0.1, y0), 10.8, y1 - y0,
                                   facecolor=clr, edgecolor="#cccccc",
                                   linewidth=0.6, zorder=0))
        ax.text(0.25, (y0 + y1) / 2, lbl, fontsize=7.5,
                color="#555555", va="center", style="italic", zorder=1)

    _box(ax, 5.5, 6.55, 3.0, 0.5, "Sachet Frontend / WhatsApp / Mobile",
         bg=CDOT_LIGHT, fontsize=8, bold=True)
    _box(ax, 3.5, 5.65, 2.5, 0.55, "queries_bp\n/api/queries",    bg=GREEN_BG, fontsize=7.5)
    _box(ax, 7.5, 5.65, 2.5, 0.55, "documents_bp\n/api/documents", bg=GREEN_BG, fontsize=7.5)

    for x, y, lbl in [
        (1.2, 4.55, "QueryService\n+ Guardrails"),
        (3.2, 4.55, "QueryAgent\nService"),
        (5.2, 4.55, "QueryIntent\nService"),
        (7.2, 4.55, "ContextProvider\nService"),
        (9.2, 4.55, "ResponseGenerator\nService"),
    ]:
        _box(ax, x, y, 1.7, 0.60, lbl, bg=ORANGE_BG, fontsize=6.8)

    for x, y, lbl in [
        (1.5, 3.55, "ChatContext\nService"),
        (3.5, 3.55, "ChatHistory\nManager"),
        (5.5, 3.55, "Creative\nReasoning"),
        (7.5, 3.55, "AdaptiveSearch\nService"),
        (9.5, 3.55, "Document\nService"),
    ]:
        _box(ax, x, y, 1.7, 0.60, lbl, bg=ORANGE_BG, fontsize=6.8)

    _box(ax, 2.0, 2.25, 2.0, 0.65, "Elasticsearch\n(Vectors + Keywords)", bg=RED_BG, fontsize=7)
    _box(ax, 5.5, 2.25, 2.0, 0.65, "MongoDB\n(Sessions + Chat)",          bg=RED_BG, fontsize=7)
    _box(ax, 9.0, 2.25, 2.0, 0.65, "SQLite in-memory\n(CSV/XLSX tables)", bg=RED_BG, fontsize=7)

    _box(ax, 1.5,  0.75, 1.8, 0.55, "C-DOT GPU Server\n(LLM Inference)",    bg="#e8d5f5", fontsize=6.8)
    _box(ax, 3.8,  0.75, 1.8, 0.55, "Ollama\n(bge-m3 Embeddings)",          bg="#e8d5f5", fontsize=6.8)
    _box(ax, 6.1,  0.75, 1.8, 0.55, "vexyl-tts\n(Indic Parler TTS)",         bg="#e8d5f5", fontsize=6.8)
    _box(ax, 8.4,  0.75, 1.8, 0.55, "IndicTrans2\n(Translation)",           bg="#e8d5f5", fontsize=6.8)
    _box(ax, 10.4, 0.75, 1.0, 0.55, "Gemma 4\n(Images)",                    bg="#e8d5f5", fontsize=6.0)

    _arrow(ax, 5.5, 6.3, 3.5, 5.93)
    _arrow(ax, 5.5, 6.3, 7.5, 5.93)
    _arrow(ax, 3.5, 5.37, 3.2, 4.85)
    _arrow(ax, 7.5, 5.37, 9.2, 4.85)
    _arrow(ax, 7.2, 4.25, 2.0, 2.58)
    _arrow(ax, 3.5, 3.25, 5.5, 2.58)
    _arrow(ax, 9.5, 3.25, 9.0, 2.58)
    _arrow(ax, 9.2, 4.25, 1.5, 1.03)
    _arrow(ax, 2.0, 1.92, 3.8, 1.03)

    return _png_bytes(fig)


# ─── Diagram 2 : Standard Query Flow ─────────────────────────────────────────

def diagram_query_flow():
    fig, ax = plt.subplots(figsize=(8, 11))
    ax.set_xlim(0, 8); ax.set_ylim(0, 11)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.set_title("Figure 3.1: Control Flow – Standard Query",
                 fontsize=10, fontweight="bold", pad=8)

    steps = [
        (4.0, 10.4, "User sends POST /api/ask\n{token, message, sessionId, chatId}",
         CDOT_LIGHT, True),
        (4.0,  9.5, "QueryService: validate JWT, extract params", GREEN_BG, False),
        (4.0,  8.6, "Guardrails: check injection, PII, XSS",      ORANGE_BG, False),
        (4.0,  7.5, "Does query need\nchat history?",             ORANGE_BG, False),
        (4.0,  6.6, "ChatHistoryManager: fetch recent messages from MongoDB", GREEN_BG, False),
        (4.0,  5.7, "QueryIntentService: classify\n(DOCUMENT / DATA / SUMMARY / HYBRID / CHAT)",
         ORANGE_BG, False),
        (4.0,  4.8, "ContextProviderService:\nhybrid search (BM25 + vector) on Elasticsearch",
         GREEN_BG, False),
        (4.0,  3.9, "ResponseGeneratorService:\nbuild grounded prompt → GPU LLM",
         GREEN_BG, False),
        (4.0,  3.0, "Output language ≠ English?\nTranslate via IndicTrans2", ORANGE_BG, False),
        (4.0,  2.1, "ChatHistoryManager:\nsave conversation turn to MongoDB", GREEN_BG, False),
        (4.0,  1.2, "Return JSON:\n{answer, context, questions, chat_context_used}",
         CDOT_LIGHT, True),
    ]

    for x, y, lbl, bg, bold in steps:
        if "?" in lbl and "chat history" not in lbl and "language" not in lbl:
            _diamond(ax, x, y, 3.8, 0.65, lbl, bg=bg)
        else:
            _box(ax, x, y, 5.8, 0.62, lbl, bg=bg, bold=bold, fontsize=8, wrap=55)

    for i in range(len(steps) - 1):
        _arrow(ax, steps[i][0], steps[i][1] - 0.31,
               steps[i+1][0], steps[i+1][1] + 0.31)

    return _png_bytes(fig)


# ─── Diagram 3 : Document Ingestion Pipeline ──────────────────────────────────

def diagram_ingestion():
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.set_xlim(0, 12); ax.set_ylim(0, 5.5)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.set_title("Figure 3.2: Deployment View – Document Ingestion Pipeline",
                 fontsize=10, fontweight="bold", pad=8)

    nodes = [
        (0.9,  2.75, "Upload\nFiles/URLs\n/api/upload",     CDOT_LIGHT),
        (2.5,  2.75, "DocumentService\nclassify_files()",    GREEN_BG),
        (4.3,  4.0,  "Doc Files\n(PDF/DOCX/\nPPTX/TXT)",    CDOT_LIGHT),
        (4.3,  2.75, "URL Content\nService (Selenium)",      ORANGE_BG),
        (4.3,  1.5,  "Data Files\n(CSV/XLSX)",               ORANGE_BG),
        (6.3,  4.0,  "extractText.py\nPyMuPDF/docx/pptx",   GREEN_BG),
        (6.3,  1.5,  "sql_db.py\npandas→SQLite",             GREEN_BG),
        (8.1,  3.2,  "upload.py\nMarkdown split\n+RecursiveChar\n1500 chars / 300 overlap",
         ORANGE_BG),
        (10.0, 3.2,  "Elasticsearch\nbge-m3 vector\nindex",  RED_BG),
        (8.1,  1.5,  "sheet_metadata\n.json",                GREEN_BG),
        (8.1,  4.7,  "Background:\ncreate_abstractive\n_summary()\nimp_sents.txt", GRAY_BG),
    ]

    for x, y, lbl, bg in nodes:
        _box(ax, x, y, 1.5, 0.85, lbl, bg=bg, fontsize=7, wrap=20)

    for x1, y1, x2, y2, lbl in [
        (0.9, 2.75, 2.5, 2.75, ""),
        (2.5, 3.18, 4.3, 4.00, "docs"),
        (2.5, 2.75, 4.3, 2.75, "URLs"),
        (2.5, 2.32, 4.3, 1.50, "data"),
        (4.3, 4.00, 6.3, 4.00, ""),
        (4.3, 2.75, 8.1, 3.20, "scraped text"),
        (4.3, 1.50, 6.3, 1.50, ""),
        (6.3, 4.00, 8.1, 3.55, "chunks"),
        (6.3, 1.50, 8.1, 1.50, ""),
        (8.1, 3.20, 10.0, 3.20, "embed"),
        (8.1, 3.62, 8.1,  4.28, ""),
    ]:
        _arrow(ax, x1, y1, x2, y2, lbl)

    return _png_bytes(fig)


# ─── Diagram 4 : RAG Pipeline ────────────────────────────────────────────────

def diagram_rag():
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 6)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.set_title("Figure 3.3: RAG Retrieval & Generation Pipeline",
                 fontsize=10, fontweight="bold", pad=8)

    _box(ax, 1.2, 5.3, 1.8, 0.6,  "User Query",                              CDOT_LIGHT, bold=True)
    _box(ax, 1.2, 4.3, 1.8, 0.6,  "Query Enhancement\n(+chat context)",      GREEN_BG)
    _box(ax, 0.5, 3.0, 1.5, 0.65, "Keyword Search\n(BM25, k=5)",             ORANGE_BG, fontsize=7)
    _box(ax, 2.2, 3.0, 1.5, 0.65, "Vector Search\n(cosine sim, k=5)",        ORANGE_BG, fontsize=7)
    _box(ax, 1.2, 1.9, 2.2, 0.65, "EnsembleRetriever\nweights [0.5, 0.5]",  RED_BG)
    _box(ax, 1.2, 0.9, 2.2, 0.65, "Top-k Chunks\n(+ full table fetch)",      GREEN_BG)

    _box(ax, 5.5, 5.3, 2.5, 0.6,  "ContextProviderService\nformatted context + citations",
         GREEN_BG, bold=True)
    _box(ax, 5.5, 4.1, 2.5, 0.75, "ResponseGeneratorService\nPrompt: system + context + question",
         ORANGE_BG, fontsize=7)
    _box(ax, 5.5, 2.9, 2.5, 0.75, "GPU LLM (C-DOT server)\ngrounded answer generation",
         RED_BG, fontsize=7.5)
    _box(ax, 5.5, 1.8, 2.5, 0.65, "Post-processing:\nJSON parse + IndicTrans2",
         GREEN_BG, fontsize=7)
    _box(ax, 5.5, 0.8, 2.5, 0.65, "Final Response\n{answer, questions, context[]}",
         CDOT_LIGHT, bold=True)

    _arrow(ax, 1.2, 5.0, 1.2, 4.6)
    _arrow(ax, 0.9, 4.0, 0.5, 3.33)
    _arrow(ax, 1.5, 4.0, 2.2, 3.33)
    _arrow(ax, 0.5, 2.68, 1.2, 2.23)
    _arrow(ax, 2.2, 2.68, 1.2, 2.23)
    _arrow(ax, 1.2, 1.58, 1.2, 1.23)
    _arrow(ax, 5.5, 5.0, 5.5, 4.48)
    _arrow(ax, 5.5, 3.73, 5.5, 3.28)
    _arrow(ax, 5.5, 2.53, 5.5, 2.13)
    _arrow(ax, 5.5, 1.48, 5.5, 1.13)
    _arrow(ax, 2.3, 0.9, 4.2, 4.1, "context chunks")
    _arrow(ax, 1.2, 5.3, 4.2, 5.3, "original query")

    ax.text(3.8, 3.0, "Elasticsearch\nIndex", fontsize=7.5, color="#555555",
            ha="center", style="italic",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=GRAY_BG, edgecolor="#cccccc"))

    return _png_bytes(fig)


# ═════════════════════════════════════════════════════════════════════════════
# DOCX HELPERS  (matching sample: plain bordered tables, no fills)
# ═════════════════════════════════════════════════════════════════════════════

def _apply_heading_style(doc, style_name, size_pt, indent_pt):
    """Ensure a heading style exists with the correct size and indent."""
    style = doc.styles[style_name]
    style.font.size = Pt(size_pt)
    style.font.bold = True
    pf = style.paragraph_format
    pf.left_indent = Pt(indent_pt)
    pf.keep_with_next = True


def _heading(doc, text, level):
    p = doc.add_heading(text, level=level)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    return p


def _body(doc, text):
    p = doc.add_paragraph(text)
    p.style = doc.styles["Normal"]
    p.paragraph_format.space_after = Pt(4)
    return p


def _section_label(doc, text):
    """14pt bold Normal — for Preface/Approval Block/Revision History/ToC labels."""
    p = doc.add_paragraph()
    p.style = doc.styles["Normal"]
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(14)
    return p


def _bullet(doc, text, level=0):
    p = doc.add_paragraph(text, style="List Bullet")
    p.paragraph_format.left_indent = Inches(0.25 * (level + 1))
    return p


def _add_figure(doc, png_buf, caption, width=Inches(6.0)):
    doc.add_picture(png_buf, width=width)
    last = doc.paragraphs[-1]
    last.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap = doc.add_paragraph(caption)
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.runs[0].italic = True
    cap.runs[0].font.size = Pt(9)
    doc.add_paragraph()


def _plain_table(doc, headers, rows, col_widths=None, bold_first_col=False):
    """
    Plain bordered table — no coloured fills, matching sample style.
    Header row: bold text.  Alternating rows: plain.
    """
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"

    # Header row
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(9)
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Data rows
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = ""
            run = cell.paragraphs[0].add_run(val)
            run.font.size = Pt(9)
            if bold_first_col and ci == 0:
                run.bold = True

    if col_widths:
        for row in table.rows:
            for i, w in enumerate(col_widths):
                row.cells[i].width = w

    doc.add_paragraph()


def _merge_row(table, row_idx):
    """Merge all cells in a row (full-width span)."""
    cells = table.rows[row_idx].cells
    cells[0].merge(cells[-1])


def _cover_table(doc):
    """
    Reproduce the C-DOT cover-page bordered table from the sample:
    Row 0 (merged): uncontrolled copy note
    Row 1 (merged): hardcopy note
    Row 2: Issued to | C-DOT | on | 18-Jun-2026 | | by | <Name> |
    Row 3 (merged): signature / blank
    Row 4 (merged 7 of 8): C-DOT name and address
    """
    table = doc.add_table(rows=5, cols=8)
    table.style = "Table Grid"

    # Row 0 — merged, uncontrolled copy note
    _merge_row(table, 0)
    table.rows[0].cells[0].text = (
        "Any softcopy in a directory other than the process repository is an Uncontrolled Copy."
    )
    table.rows[0].cells[0].paragraphs[0].runs[0].font.size = Pt(8)

    # Row 1 — merged, hardcopy note
    _merge_row(table, 1)
    table.rows[1].cells[0].text = (
        "A hardcopy is an Uncontrolled Copy unless signed by an authorised signatory."
    )
    table.rows[1].cells[0].paragraphs[0].runs[0].font.size = Pt(8)

    # Row 2 — "Issued to" detail row
    r2_data = ["Issued to", "C-DOT", "on", "18-Jun-2026", "", "by", "<Authorised Signatory>", ""]
    for ci, val in enumerate(r2_data):
        cell = table.rows[2].cells[ci]
        cell.text = ""
        run = cell.paragraphs[0].add_run(val)
        run.font.size = Pt(9)
        if val in ("Issued to", "on", "by"):
            run.bold = True

    # Row 3 — blank / signature row
    _merge_row(table, 3)
    table.rows[3].cells[0].text = ""
    # add some vertical space
    for _ in range(2):
        table.rows[3].cells[0].add_paragraph("")

    # Row 4 — merge first 7 cols, C-DOT address
    cells = table.rows[4].cells
    cells[0].merge(cells[6])
    addr_cell = table.rows[4].cells[0]
    addr_cell.text = ""
    for _ in range(3):
        addr_cell.add_paragraph("")
    p = addr_cell.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("CENTRE FOR DEVELOPMENT OF TELEMATICS")
    run.bold = True; run.font.size = Pt(11)

    p2 = addr_cell.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run("C-DOT Campus, Mehrauli, New Delhi 110030, India")
    r2.font.size = Pt(9)

    p3 = addr_cell.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r3 = p3.add_run("Electronic City (phase-1), Hosur Road, Bengaluru 560100, India")
    r3.font.size = Pt(9)

    for _ in range(3):
        addr_cell.add_paragraph("")

    doc.add_paragraph()


# ═════════════════════════════════════════════════════════════════════════════
# DOCUMENT ASSEMBLY
# ═════════════════════════════════════════════════════════════════════════════

def build_document():
    print("Generating diagrams…")
    arch_png   = diagram_system_architecture()
    qflow_png  = diagram_query_flow()
    ingest_png = diagram_ingestion()
    rag_png    = diagram_rag()

    print("Building document…")
    doc = Document()

    # ── Normal body text: 11pt (matches template body run size) ──
    doc.styles["Normal"].font.size = Pt(11)

    # ── Heading styles to match sample ──
    _apply_heading_style(doc, "Heading 1", 12, 21.6)
    _apply_heading_style(doc, "Heading 2", 11, 22.5)
    _apply_heading_style(doc, "Heading 3", 11, 21.6)
    _apply_heading_style(doc, "Heading 4", 12, 36.0)

    # ── Page margins: 1 inch all around (matching sample) ──
    for section in doc.sections:
        section.top_margin    = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin   = Inches(1)
        section.right_margin  = Inches(1)

    # ─────────────────────────────────────────────────────────────────────────
    # COVER PAGE — matching sample layout
    # ─────────────────────────────────────────────────────────────────────────
    def _cover_line(text, size_pt, bold=False):
        p = doc.add_paragraph()
        p.style = doc.styles["Normal"]
        p.paragraph_format.space_after = Pt(2)
        if text:
            run = p.add_run(text)
            run.font.size = Pt(size_pt)
            run.bold = bold

    _cover_line("Design",                        20, bold=True)
    _cover_line("CCP-SAC-ARC-01",                12, bold=True)
    _cover_line("",                              11)
    _cover_line("Version 1.0",                   12, bold=True)
    _cover_line("[Draft 1]",                     12, bold=True)
    _cover_line("",                              11)
    _cover_line("Template: PM-QM-TPL-SYSA-C01 v01", 11, bold=True)

    for _ in range(5):
        doc.add_paragraph()

    for label in ["Architecture Design", "For",
                  "AI Chatbot Backend (Sachet Agent)"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(label)
        run.bold = True
        run.font.size = Pt(20)

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr = p.add_run("Released on: 18-Jun-2026")
    rr.font.size = Pt(12)
    rr.bold = True

    for _ in range(6):
        doc.add_paragraph()

    _cover_table(doc)
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # APPROVAL BLOCK
    # ─────────────────────────────────────────────────────────────────────────
    _section_label(doc, "Approval Block")
    # 3-row × 5-col approval table matching template: row0 = "Version" | "Approved by" (merged)
    # row1 = sub-headers, row2 = data
    _atbl = doc.add_table(rows=3, cols=5)
    _atbl.style = "Table Grid"
    for _ci, _cw in enumerate([Inches(0.9), Inches(1.3), Inches(1.3), Inches(1.2), Inches(1.0)]):
        for _ri in range(3):
            _atbl.cell(_ri, _ci).width = _cw
    # Row 0: merged "Approved by" header
    _atbl.cell(0, 0).text = "Version"
    _atbl.cell(0, 0).paragraphs[0].runs[0].bold = True
    _mc = _atbl.cell(0, 1).merge(_atbl.cell(0, 4))
    _mc.text = "Approved by"
    _mc.paragraphs[0].runs[0].bold = True
    # Row 1: sub-headers
    for _j, _h in enumerate(["Version", "Role", "Name", "Signature", "Date"]):
        _c = _atbl.cell(1, _j)
        _c.text = _h
        _c.paragraphs[0].runs[0].bold = True
    # Row 2: data
    for _j, _d in enumerate(["1.0", "<Process Responsibility>", "<Name>", "[signed]", "dd.mm.yyyy"]):
        _atbl.cell(2, _j).text = _d

    # ─────────────────────────────────────────────────────────────────────────
    # REVISION HISTORY
    # ─────────────────────────────────────────────────────────────────────────
    _section_label(doc, "Revision History")
    _body(doc, "This document replaces")
    _body(doc, "Document code\t: CCP-SAC-ARC-01[-V1] v1.0 [d1]")
    _body(doc, "Document name\t: Architecture Design for AI Chatbot Backend (Sachet Agent)")
    doc.add_paragraph()
    _plain_table(doc,
        ["Version, Draft", "Dated", "Author(s)", "Summary of changes",
         "Reference sections", "Reason of change and remarks"],
        [["v1.0 [d1]", "18-Jun-2026", "Carnot Research / C-DOT Team",
          "Initial draft", "All", "First submission per client requirement"]],
        col_widths=[Inches(0.9), Inches(0.9), Inches(1.4), Inches(1.5),
                    Inches(0.9), Inches(0.95)])

    # ─────────────────────────────────────────────────────────────────────────
    # PARTICIPATION
    # ─────────────────────────────────────────────────────────────────────────
    _section_label(doc, "Participation")
    doc.add_paragraph()
    _body(doc, "This document has been authored/modified by")
    _body(doc, "<Primary Author Name(s)>")
    _body(doc, "with contributions from")
    _body(doc, "<Contributing Team Member(s)>")
    doc.add_paragraph()
    _body(doc, "Comments, suggestions and queries pertaining to this document should be addressed to")
    _body(doc, "<Custodian's designation>")
    _body(doc, "Name: <Custodian's name>")
    _body(doc, "e-mail: <E-mail address>")
    doc.add_paragraph()

    # ─────────────────────────────────────────────────────────────────────────
    # TABLE OF CONTENTS / FIGURES / TABLES  (placeholders)
    # ─────────────────────────────────────────────────────────────────────────
    _section_label(doc, "Table of Contents")
    _body(doc, "<Generated table of contents>")
    doc.add_paragraph()
    _section_label(doc, "List of Tables")
    _body(doc, "<Generated list of tables>")
    doc.add_paragraph()
    _section_label(doc, "List of Figures")
    _body(doc, "<Generated list of figures>")
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # PREFACE
    # ─────────────────────────────────────────────────────────────────────────
    _section_label(doc, "Preface")
    doc.add_paragraph()

    _body(doc,
        "This document presents the High Level Design (HLD) for the AI Chatbot Backend "
        "component of C-DOT's Sachet platform — a Retrieval-Augmented Generation (RAG) "
        "system enabling intelligent document Q&A in 23 Indian languages."
    )
    doc.add_paragraph()
    _body(doc,
        "Purpose: To define the system architecture, retrieval pipeline, chunking and embedding "
        "strategy, model selection rationale, and scalability considerations for the Sachet AI "
        "Chatbot Backend."
    )
    doc.add_paragraph()
    _body(doc,
        "Scope & Coverage: Backend REST API service only. Frontend applications consuming the API "
        "are out of scope. Covers component decomposition, data organisation, interfaces, and design "
        "decisions."
    )
    doc.add_paragraph()
    _body(doc,
        "Conventions: In diagrams — rounded blue boxes: start/end; green boxes: processing steps; "
        "orange: decisions/parameters; red: data stores."
    )
    doc.add_paragraph()
    _body(doc,
        "Intended Readers: Software architects, backend engineers, and technical reviewers "
        "from C-DOT and the implementing team."
    )
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # §1 INTRODUCTION
    # ─────────────────────────────────────────────────────────────────────────
    _heading(doc, "Introduction", 1)
    doc.add_paragraph()

    _heading(doc, "Objective and background", 2)
    doc.add_paragraph()
    _body(doc,
        "The Sachet AI Chatbot Backend is a Retrieval-Augmented Generation (RAG) platform "
        "built for C-DOT's Sachet initiative. It enables users to upload heterogeneous documents "
        "(PDF, DOCX, PPTX, TXT, CSV, XLSX) or web URLs and interact with the content through a "
        "conversational interface. The system retrieves relevant document chunks from an "
        "Elasticsearch vector store and feeds them to a GPU-hosted Large Language Model (LLM) "
        "to produce cited, grounded answers."
    )
    doc.add_paragraph()
    _body(doc,
        "The backend was derived from Carnot Research's icarKno product and customised to run on "
        "C-DOT's internal GPU infrastructure, supporting 23 Indian languages via IndicTrans2 and "
        "on-premise TTS/STT via AI4Bharat models."
    )
    doc.add_paragraph()

    _heading(doc, "Scope", 2)
    doc.add_paragraph()
    _body(doc, "The following capabilities are in scope:")
    doc.add_paragraph()
    for item in [
        "Document ingestion: multi-format text extraction, chunking, vector embedding, Elasticsearch indexing.",
        "Query processing: intent classification, hybrid search (BM25 + vector), context retrieval, LLM response generation.",
        "Creative (adaptive) mode: iterative multi-step search with LLM evaluation, delivered via SSE streaming.",
        "Chat history management: multi-chat sessions persisted in MongoDB.",
        "Multilingual support: 23 Indian languages via IndicTrans2 translation.",
        "Speech services: TTS via ai4bharat/indic-parler-tts (vexyl-tts) and STT via ai4bharat/indic-conformer (vexyl-stt).",
        "Security guardrails: prompt injection, PII, and XSS detection.",
        "REST API for integration with frontend applications (web, WhatsApp bot, mobile).",
    ]:
        _bullet(doc, item)
    doc.add_paragraph()

    _heading(doc, "References", 2)
    doc.add_paragraph()
    for ref in [
        "[1] C-DOT Sachet Platform Requirements (internal document)",
        "[2] Flask / FastAPI Documentation — https://fastapi.tiangolo.com",
        "[3] Elasticsearch Reference — https://www.elastic.co/guide/",
        "[4] LangChain Documentation — https://python.langchain.com",
        "[5] Indic Parler TTS — ai4bharat/indic-parler-tts (HuggingFace)",
        "[6] Indic Conformer STT — ai4bharat/indic-conformer-600m-multilingual (HuggingFace)",
        "[7] IndicTrans2 — https://github.com/AI4Bharat/IndicTrans2",
        "[8] BGE-M3 Embedding Model — https://huggingface.co/BAAI/bge-m3",
        "[9] Distil-Whisper — distil-whisper/distil-medium.en (HuggingFace)",
    ]:
        _body(doc, ref)
    doc.add_paragraph()

    _heading(doc, "Definitions, acronyms and terminology", 2)
    doc.add_paragraph()

    _heading(doc, "Definitions", 3)
    doc.add_paragraph()
    _plain_table(doc,
        ["Term", "Definition"],
        [
            ["Knowledge Container",
             "A named session grouping a set of user-uploaded documents and their associated Elasticsearch index."],
            ["Chunk",
             "A fixed-size text segment extracted from a document, stored as a searchable unit in Elasticsearch."],
            ["Hybrid Search",
             "Combination of BM25 keyword and vector similarity search merged via EnsembleRetriever with equal weights [0.5, 0.5]."],
            ["Grounded Answer",
             "An LLM response restricted to information present in the retrieved context, with source citations."],
            ["Creative Mode",
             "Advanced query mode that iteratively refines searches (up to 3 rounds) until the LLM evaluates results as sufficient."],
            ["Guardrails",
             "Input sanitisation layer checking for prompt injection, PII, and XSS before any LLM call."],
        ],
        col_widths=[Inches(1.8), Inches(4.8)])

    _heading(doc, "Acronyms", 3)
    doc.add_paragraph()
    _plain_table(doc,
        ["Acronym", "Expansion"],
        [
            ["RAG",  "Retrieval-Augmented Generation"],
            ["LLM",  "Large Language Model"],
            ["API",  "Application Programming Interface"],
            ["JWT",  "JSON Web Token"],
            ["BM25", "Best Match 25 (probabilistic keyword ranking)"],
            ["ES",   "Elasticsearch"],
            ["SSE",  "Server-Sent Events"],
            ["TTS",  "Text-to-Speech"],
            ["STT",  "Speech-to-Text"],
            ["ASR",  "Automatic Speech Recognition"],
            ["NLP",  "Natural Language Processing"],
            ["GPU",  "Graphics Processing Unit"],
            ["HLD",  "High Level Design"],
            ["REST", "Representational State Transfer"],
        ],
        col_widths=[Inches(1.2), Inches(5.4)])
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # §2 INTRODUCTION TO THE SOFTWARE SUBSYSTEM
    # ─────────────────────────────────────────────────────────────────────────
    _heading(doc, "Introduction to the software subsystem", 1)
    doc.add_paragraph()
    _body(doc,
        "The Sachet AI Chatbot Backend is a stateless RESTful service built on FastAPI, "
        "exposing two router groups — query management and document management — each under "
        "the /api/ prefix. All business logic is encapsulated in singleton service classes "
        "with lazy initialisation. The system interfaces with Elasticsearch for document "
        "retrieval, MongoDB for session and chat persistence, and a C-DOT GPU server for LLM "
        "inference."
    )
    doc.add_paragraph()

    _heading(doc, "Properties", 3)
    doc.add_paragraph()
    _plain_table(doc,
        ["Property", "Value"],
        [
            ["Language / Runtime",    "Python 3.10+"],
            ["Web Framework",         "FastAPI + Slowapi (rate limiting) + Starlette CORS"],
            ["Service Pattern",       "Singleton services with lazy initialisation"],
            ["API Style",             "REST (JSON); StreamingResponse for creative mode SSE"],
            ["Authentication",        "JWT (PyJWT 2.8.0) — Bearer token or form field"],
            ["Rate Limiting",         "Slowapi: 20 req/min (trial), 10 req/min (TTS)"],
            ["Deployment Port",       "8000 (Uvicorn / configurable)"],
            ["Supported File Formats","PDF, DOCX, DOC, TXT, PPTX, CSV, XLSX"],
            ["Max File Size",         "50 MB per file"],
            ["Languages Supported",   "23 (English + 22 scheduled Indian languages)"],
            ["API Documentation",     "Auto-generated Swagger UI at /docs"],
        ],
        col_widths=[Inches(2.2), Inches(4.4)])

    _heading(doc, "Functionality", 3)
    doc.add_paragraph()
    _body(doc, "The subsystem provides six primary capabilities:")
    for item in [
        "Document Ingestion — Upload and process documents; extract text, chunk, embed, and index into Elasticsearch.",
        "Intelligent Query Processing — Classify query intent (5 types) and retrieve relevant context via hybrid search.",
        "LLM Response Generation — Generate grounded, cited answers using the C-DOT GPU-hosted language model.",
        "Adaptive (Creative) Mode — Iterative multi-step search with LLM-based sufficiency evaluation, streamed via SSE.",
        "Chat History Management — Multi-chat session persistence with rename, notes, and statistics in MongoDB.",
        "Multilingual & Speech — Translate responses to 23 Indian languages; TTS via indic-parler-tts; STT via indic-conformer.",
    ]:
        _bullet(doc, item)
    doc.add_paragraph()
    _add_figure(doc, arch_png,
                "Figure 2-1: Sachet AI Chatbot Backend — System Architecture",
                width=Inches(6.5))
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # §3 DESIGN CONSIDERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    _heading(doc, "Design considerations", 1)
    doc.add_paragraph()

    _heading(doc, "Design goals", 2)
    doc.add_paragraph()
    _plain_table(doc,
        ["Goal", "Description"],
        [
            ["Accuracy",
             "Answers grounded strictly in retrieved context — no hallucination. Enforced via strict "
             "prompt engineering: 'Use ONLY information in the CONTEXT.' "],
            ["Low Latency",
             "Standard queries target < 10 seconds. Fast LLM variant (512 tokens, temp 0.3) used for "
             "classification and evaluation sub-calls to minimise overhead."],
            ["Multilingual",
             "Accepts queries in 23 Indian languages and returns translated responses without "
             "retraining the LLM. Translation handled post-generation via IndicTrans2."],
            ["Scalability",
             "Stateless FastAPI workers scalable horizontally; Elasticsearch scales via shard "
             "replication; MongoDB handles distributed session state."],
            ["Privacy / On-Premise",
             "All LLM inference, embedding, TTS, STT, and translation services run on C-DOT "
             "infrastructure — no document data leaves the network."],
            ["Security",
             "JWT authentication on all authenticated endpoints; GuardrailProcessor blocks prompt "
             "injection, PII, and XSS before any LLM call."],
            ["Extensibility",
             "Service-oriented singleton pattern allows new services to be added without modifying "
             "existing routes. Skills and intents are data-configurable."],
        ],
        col_widths=[Inches(1.5), Inches(5.1)])
    doc.add_paragraph()

    _heading(doc, "Constraints and limitations", 2)
    doc.add_paragraph()
    for item in [
        "LLM inference depends on the C-DOT GPU server — unavailability halts all query responses; no local fallback configured.",
        "Embeddings require Ollama running with bge-m3:latest at document ingestion time.",
        "CSV/XLSX data loaded into SQLite in-memory tables — lost on server restart; users must re-upload structured data.",
        "Creative mode capped at 3 search iterations and 120 seconds maximum processing time.",
        "File types restricted to PDF, DOCX, TXT, PPTX, CSV, XLSX (max 50 MB each).",
        "Slowapi rate limiting uses per-worker in-memory store by default — Redis required for multi-worker deployments.",
        "No built-in document access control — all documents in a session are accessible to the session owner.",
    ]:
        _bullet(doc, item)
    doc.add_paragraph()

    _heading(doc, "Assumptions", 2)
    doc.add_paragraph()
    for item in [
        "The C-DOT GPU server is accessible from the backend host and supports OpenAI-compatible chat API format.",
        "An Elasticsearch 8.x cluster is available and reachable at ES_BASE_URL.",
        "MongoDB instance is running and accessible via MONGO_URL.",
        "Ollama is running on the backend host (or accessible network address) with bge-m3:latest loaded for embeddings.",
        "vexyl-tts and vexyl-stt WebSocket servers are running on-premise at configured URLs.",
        "IndicTrans2 translation server is running for multilingual query/response support.",
        "Users authenticate with JWT tokens issued by the parent Sachet application.",
    ]:
        _bullet(doc, item)
    doc.add_paragraph()

    _heading(doc, "Alternate approaches", 2)
    doc.add_paragraph()

    _heading(doc, "Options", 3)
    doc.add_paragraph()
    _plain_table(doc,
        ["Area", "Option A (Rejected)", "Option B (Selected)"],
        [
            ["Search Strategy",
             "Pure keyword search (BM25 only) — fast but misses semantic matches on paraphrased queries.",
             "Hybrid search: BM25 + vector similarity (EnsembleRetriever [0.5, 0.5]) — balances recall and precision."],
            ["LLM Hosting",
             "Ollama on local server (7–13B models) — easy setup but limited GPU and lower quality.",
             "C-DOT GPU server (70B model, OpenAI-compatible) — higher quality, centralised management."],
            ["TTS",
             "ElevenLabs cloud API — high quality but external dependency, per-character cost, data egress.",
             "ai4bharat/indic-parler-tts via vexyl-tts — on-premise, no API cost, native Indian language support."],
            ["STT",
             "Whisper large-v3 (generic) — good English ASR but higher WER on Indian language accents.",
             "ai4bharat/indic-conformer-600m-multilingual — purpose-built for Indian languages; distil-whisper for English."],
            ["Structured Data",
             "Direct MySQL integration — requires schema migration per upload.",
             "SQLite in-memory per session via SQLAlchemy — zero schema overhead, LLM-generated SQL."],
            ["Streaming Responses",
             "Polling endpoint — client polls every N seconds for creative mode progress.",
             "SSE via FastAPI StreamingResponse — real-time progress events, no polling overhead."],
        ],
        col_widths=[Inches(1.2), Inches(2.6), Inches(2.8)])

    _heading(doc, "Criteria for evaluating the options", 3)
    doc.add_paragraph()
    for item in [
        "Answer accuracy and recall — ability to find relevant content for paraphrased or ambiguous queries.",
        "Latency — total round-trip time from query to response.",
        "Data privacy — no document content leaving C-DOT infrastructure.",
        "Infrastructure cost and operational complexity.",
        "Multilingual capability for 23 Indian languages without model fine-tuning.",
        "Extensibility — ease of swapping components in future.",
    ]:
        _bullet(doc, item)
    doc.add_paragraph()

    _heading(doc, "Selected approach and the rationale for its selection", 3)
    doc.add_paragraph()
    _body(doc,
        "Hybrid RAG with C-DOT GPU-hosted LLM was selected. The EnsembleRetriever combines "
        "BM25 keyword precision with vector semantic recall. The GPU server enables 70B-parameter "
        "models for answer quality unreachable by local 7–13B Ollama models. On-premise vexyl-tts "
        "and vexyl-stt replace cloud speech APIs, eliminating data egress. SQLite in-memory "
        "avoids per-user database schema management. SSE streaming delivers responsive UX for "
        "complex multi-iteration creative queries."
    )
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # §4 HIGH LEVEL DESIGN DECOMPOSITION
    # ─────────────────────────────────────────────────────────────────────────
    _heading(doc, "High level design decomposition", 1)
    doc.add_paragraph()
    _body(doc,
        "The subsystem is decomposed into seven logical modules. The table below "
        "summarises each module and its functionality."
    )
    doc.add_paragraph()
    _body(doc, "Table 4-1: Software module / component summary")
    doc.add_paragraph()
    _plain_table(doc,
        ["#", "Software module / component name", "Functionality provided"],
        [
            ["1", "API Layer",
             "FastAPI routers (queries, documents). JWT dependency injection, Slowapi rate limiting, "
             "StreamingResponse for creative mode, auto-generated Swagger UI at /docs."],
            ["2", "Query Processing",
             "QueryService (gateway + guardrails), QueryAgentService (orchestrator — routes standard "
             "vs creative), QueryIntentService (5-class LLM-based intent classifier)."],
            ["3", "Retrieval Pipeline",
             "ContextProviderService (hybrid search orchestrator), AdaptiveSearchService "
             "(iterative search, up to 3 rounds), ResultEvaluationService (LLM sufficiency scoring)."],
            ["4", "Response Generation",
             "ResponseGeneratorService (prompt engineering + LLM invocation), "
             "ResultSynthesisService (multi-source answer merging), "
             "CreativeReasoningService (adaptive pipeline + SSE events)."],
            ["5", "Document Ingestion",
             "DocumentService (orchestrator), extractText.py (PDF/DOCX/PPTX/TXT), "
             "upload.py (two-stage chunking), ElasticDocumentManager (bulk ES indexing), "
             "URLContentService (Selenium + BeautifulSoup + YouTube)."],
            ["6", "Data & Session Layer",
             "Elasticsearch (vector + keyword), MongoDB (chat + sessions via Beanie ODM), "
             "SQLite in-memory (CSV/XLSX), local filesystem (raw files)."],
            ["7", "Utility Services",
             "LLMService (GPUServerChatModel wrapper), vexyl-tts (indic-parler-tts), "
             "vexyl-stt (indic-conformer + distil-whisper), Gemma 4 (image captioning), "
             "GuardrailProcessor, IndicTrans2 (translation)."],
        ],
        col_widths=[Inches(0.3), Inches(2.2), Inches(4.1)])

    _heading(doc, "Decomposition description", 2)
    doc.add_paragraph()

    for title, ident, mtype, purpose, bullets in [
        ("4.1.1  API Layer",
         "API Layer", "FastAPI APIRouter",
         "Routes HTTP requests to service methods. Enforces JWT authentication via dependency "
         "injection (get_current_user), Slowapi rate limiting, and CORS. Emits SSE events for "
         "creative-mode streams. Auto-generates Swagger UI documentation.",
         [
             "POST /api/ask — authenticated document query",
             "GET /api/ask-stream — SSE creative mode stream",
             "POST /api/ask-tts — query with TTS audio response (WAV streaming)",
             "POST /api/upload — create knowledge container",
             "POST /api/add-upload — append files to existing container",
             "GET /api/get-containers — list user knowledge containers",
             "DELETE /api/delete-container — remove container + Elasticsearch index + files",
             "GET/PUT/DELETE /api/chat-history/* — full chat CRUD with pagination and notes",
         ]),
        ("4.1.2  Query Processing",
         "Query Processing", "Orchestration / Classification",
         "QueryService validates input and applies GuardrailProcessor checks before any LLM call. "
         "QueryAgentService decides routing: standard intent-based flow or creative adaptive flow. "
         "QueryIntentService classifies queries into one of five intents using a fast LLM call.",
         [
             "Intents: GENERAL_CHAT, SUMMARY, DOCUMENT, DATA_QUERY, HYBRID",
             "Chat context detection: 3-tier (regex pattern → LLM → weighted combine: 70% pattern, 30% LLM)",
             "Creative mode guards: explicit mode flag, query ≥3 words, non-trial user, resources exist",
             "Guardrails check: prompt injection, PII (email/phone/SSN), XSS, SQL injection patterns",
         ]),
        ("4.1.3  Retrieval Pipeline",
         "Retrieval Pipeline", "Search & Evaluation",
         "ContextProviderService retrieves document chunks using a two-arm hybrid search. "
         "AdaptiveSearchService iterates up to 3 rounds for creative queries. "
         "ResultEvaluationService scores result sufficiency (0–1) via LLM or heuristic fallback.",
         [
             "BM25 keyword retrieval: k=5, Elasticsearch BM25 ranking",
             "Vector retrieval: k=5, cosine similarity on bge-m3 embeddings",
             "EnsembleRetriever: Reciprocal Rank Fusion, weights [0.5, 0.5]",
             "Full table fetch: when partial table chunk in top-k, all chunks for that table_id fetched",
             "Adaptive threshold: starts 0.7, decreases 0.1 per iteration (floor 0.5)",
             "Deduplication: content fingerprint (first 50 + last 50 chars of normalised text)",
             "Max 5 text chunks + unlimited table chunks (up to 15 total per response)",
         ]),
        ("4.1.4  Response Generation",
         "Response Generation", "Prompt Engineering + LLM Invocation",
         "ResponseGeneratorService constructs specialised prompts per query type (document / data / "
         "hybrid / summary / chat) enforcing strict grounding. LLM always answers in English; "
         "IndicTrans2 translates post-generation. CreativeReasoningService orchestrates the full "
         "adaptive pipeline and yields SSE progress events.",
         [
             "Prompt rule: 'Use ONLY information in the CONTEXT — do not use prior knowledge'",
             "LLM variants: fast (512 tok, 0.3 temp), standard (default, 0.7), comprehensive (2048, 0.5), creative (1500, 0.9), code/SQL (2048, 0.1)",
             "JSON response parsing with nested fallback (handles malformed LLM output)",
             "SSE events emitted: thinking_start → search_start → search_complete → analyzing → synthesis_start → answer_chunk → questions → complete",
             "Max creative mode time: 120 seconds",
         ]),
        ("4.1.5  Document Ingestion",
         "Document Ingestion", "File Processing + Indexing",
         "DocumentService classifies uploads, orchestrates extraction and indexing. "
         "Abstractive summarisation (BERT extractive → LLM abstractive) runs in a background thread. "
         "CSV/XLSX files loaded into SQLite in-memory tables for NL→SQL querying.",
         [
             "Stage 1 chunking: MarkdownHeaderTextSplitter (respects #/##/### document structure)",
             "Stage 2 chunking: RecursiveCharacterTextSplitter (chunk_size=1500, overlap=300)",
             "Embedding: OllamaEmbeddings with bge-m3:latest → ElasticsearchStore (LangChain)",
             "Chunk metadata: source, filename, page, content_type (text/table), table_id",
             "URL ingestion: Selenium (dynamic pages) + BeautifulSoup (static) + YouTube transcript API",
             "Image captioning: Gemma 4 on C-DOT GPU server — captions injected into document context",
         ]),
    ]:
        _heading(doc, title, 3)
        _plain_table(doc,
            ["Attribute", "Value"],
            [
                ["Identification", ident],
                ["Type",           mtype],
                ["Purpose",        purpose],
            ],
            col_widths=[Inches(1.3), Inches(5.3)])
        for b in bullets:
            _bullet(doc, b)
        doc.add_paragraph()

    _heading(doc, "Embedding approach", 2)
    doc.add_paragraph()
    _body(doc,
        "Dense vector embeddings convert document chunks and queries into high-dimensional "
        "vectors enabling semantic similarity search independent of exact wording."
    )
    doc.add_paragraph()
    _plain_table(doc,
        ["Property", "Value"],
        [
            ["Model",               "BAAI/bge-m3"],
            ["Vector Dimensions",   "1024"],
            ["Max Input Tokens",    "8192"],
            ["Languages",           "100+ (covers all 23 Indian languages used by Sachet)"],
            ["Similarity Metric",   "Cosine similarity"],
            ["Serving",             "Ollama (OLLAMA_BASE_URL) — on-premise GPU or CPU host"],
            ["LangChain Wrapper",   "OllamaEmbeddings (langchain-ollama)"],
            ["Ingestion Cost",      "One-time per chunk at upload — not on query critical path"],
        ],
        col_widths=[Inches(2.0), Inches(4.6)])
    doc.add_paragraph()
    _body(doc, "Why BGE-M3 over alternatives:")
    _plain_table(doc,
        ["Model", "Multilingual", "On-Premise", "Why not selected"],
        [
            ["BAAI/bge-m3 ✓ (selected)", "Yes — 100+ langs", "Yes (Ollama)",
             "Best MTEB multilingual score + 8K context + fully on-premise"],
            ["all-MiniLM-L6-v2",         "No (English only)", "Yes",
             "English-only; fails 23 Indian language requirement"],
            ["OpenAI text-embedding-3-small", "Yes", "No (cloud)",
             "Cloud dependency — violates C-DOT data privacy requirement"],
            ["multilingual-e5-large",    "Yes", "Yes",
             "Good alternative but 512-token limit vs bge-m3's 8K for long PDF pages"],
        ],
        col_widths=[Inches(1.8), Inches(1.1), Inches(0.9), Inches(2.8)])
    doc.add_paragraph()

    _heading(doc, "Model selection rationale", 2)
    doc.add_paragraph()
    _plain_table(doc,
        ["Role", "Selected Model", "Alternatives Considered", "Rationale"],
        [
            ["LLM (Inference)",
             "C-DOT GPU Server\n70B parameter model",
             "Ollama 7B/13B local,\nGPT-4 (cloud),\nLlama 3 self-hosted",
             "70B model delivers higher quality answers. On-premise meets C-DOT data privacy. "
             "Cloud LLMs rejected for data privacy."],
            ["Embedding",
             "BAAI/bge-m3\n(Ollama)",
             "all-MiniLM-L6-v2,\nmultilingual-e5-large,\nOpenAI text-embedding-3-small",
             "Only bge-m3 combines 100+ language support, 8K context, strong MTEB scores, "
             "and fully on-premise deployment."],
            ["TTS",
             "ai4bharat/indic-parler-tts\n(vexyl-tts)",
             "ElevenLabs API,\nGoogle TTS,\nAzure TTS",
             "Purpose-built for Indian languages. On-premise via vexyl-tts — no external API "
             "cost or data egress. ElevenLabs and cloud TTS rejected for privacy and cost."],
            ["STT (Indian)",
             "ai4bharat/indic-conformer\n-600m-multilingual\n(vexyl-stt)",
             "Whisper large-v3,\nGoogle Speech API",
             "Fine-tuned on Indian language corpora with superior WER vs generic multilingual "
             "models. On-premise via vexyl-stt."],
            ["STT (English)",
             "distil-whisper/\ndistil-medium.en\n(vexyl-stt)",
             "Whisper large-v3,\nWhisper base",
             "6× faster than Whisper large-v3 with <1% WER increase on English. "
             "Sufficient for conversational queries."],
            ["Image Captioning",
             "Gemma 4\n(C-DOT GPU server)",
             "LLaVA, BLIP-2,\nGPT-4V (cloud)",
             "Runs on the same C-DOT GPU infrastructure. Provides detailed captions of "
             "charts, tables, and diagrams in uploaded documents."],
            ["Translation",
             "IndicTrans2\n(remote inference server)",
             "Google Translate API,\nAzure Translator,\nNLLB-200",
             "State-of-the-art for English↔Indian language pairs (AI4Bharat). "
             "On-premise — no per-character cost or data egress."],
        ],
        col_widths=[Inches(0.9), Inches(1.2), Inches(1.4), Inches(3.1)])
    doc.add_paragraph()

    _heading(doc, "Retrieval pipeline", 2)
    doc.add_paragraph()
    _body(doc,
        "The retrieval pipeline converts a user query into a ranked set of document chunks "
        "passed to the LLM for answer generation. Two modes operate:"
    )
    doc.add_paragraph()
    _heading(doc, "Standard retrieval (single-pass)", 3)
    doc.add_paragraph()
    _plain_table(doc,
        ["Step", "Component", "Detail"],
        [
            ["1. Query Enhancement",
             "ContextProviderService\n+ ChatContextService",
             "If chat history context needed (detected via 3-tier pattern+LLM), query is "
             "augmented with relevant prior conversation turns."],
            ["2. Keyword Search",
             "ElasticRetriever\n(BM25)",
             "BM25 probabilistic ranking over raw text fields. k=5 top results. "
             "Excels at exact terms, acronyms, precise phrases."],
            ["3. Vector Search",
             "ElasticRetriever\n(cosine similarity)",
             "Dense vector search using bge-m3 query embedding. k=5 top results. "
             "Excels at semantic/paraphrase matches."],
            ["4. Ensemble Merge",
             "EnsembleRetriever\n(LangChain RRF)",
             "Reciprocal Rank Fusion merges BM25 and vector result lists. "
             "Weights [0.5, 0.5]. Final list deduplicated and re-ranked."],
            ["5. Full Table Fetch",
             "get_full_table_chunks()",
             "If any top-k chunk has content_type='table', ALL chunks for that "
             "table_id are fetched — prevents partial table answers."],
            ["6. Context Formatting",
             "ContextProviderService",
             "Numbered citations: [N] <text> (source: filename, page: N). "
             "Max 5 text + up to 15 total chunks including tables."],
        ],
        col_widths=[Inches(1.3), Inches(1.5), Inches(3.8)])
    doc.add_paragraph()

    _heading(doc, "Adaptive retrieval (creative mode — iterative)", 3)
    doc.add_paragraph()
    _plain_table(doc,
        ["Iteration", "Action", "Outcome"],
        [
            ["1",
             "Enhanced query → hybrid search → LLM evaluates sufficiency "
             "(ResultEvaluationService, confidence 0.0–1.0)",
             "Confidence ≥ 0.7 → proceed to synthesis. Else → iteration 2."],
            ["2–3",
             "LLM generates 2–3 focused sub-queries targeting missing aspects. "
             "Each runs a separate hybrid search. Results merged + deduplicated.",
             "Re-evaluate combined results. Threshold decreases 0.1 per iteration "
             "(floor 0.5). Break when sufficient or max 3 iterations reached."],
            ["Synthesis",
             "All collected chunks → ResultSynthesisService → LLM synthesises "
             "comprehensive cited answer.",
             "Answer + follow-up questions returned. Capped at 120 seconds."],
        ],
        col_widths=[Inches(0.8), Inches(3.5), Inches(2.3)])

    _add_figure(doc, qflow_png,
                "Figure 4-1: Standard Query Flow",
                width=Inches(4.8))
    _add_figure(doc, ingest_png,
                "Figure 4-2: Document Ingestion Pipeline",
                width=Inches(6.5))
    _add_figure(doc, rag_png,
                "Figure 4-3: RAG Retrieval & Generation Pipeline",
                width=Inches(6.0))

    _heading(doc, "Data organisation", 2)
    doc.add_paragraph()
    _plain_table(doc,
        ["Store", "Collection / Index", "Contents", "Persistence"],
        [
            ["Elasticsearch", "<user_email><session_id>",
             "Document chunks with text + bge-m3 vector embeddings. "
             "Metadata: source, filename, page, content_type, table_id.",
             "Persistent"],
            ["MongoDB — chat_sessions", "Per user_session + chat_id",
             "Chat messages: role, content, timestamp, message_id, query_type, save_to_note.",
             "Persistent"],
            ["MongoDB — chat_names", "Per user_session + chat_id",
             "Chat display names and creation timestamps.",
             "Persistent"],
            ["MongoDB — sessions", "Per user email",
             "Knowledge container metadata: session_id, files, name, timestamps.",
             "Persistent"],
            ["SQLite (in-memory)", "Per CSV/XLSX upload",
             "Tabular data via pandas. Schema in sheet_metadata.json.",
             "Ephemeral — lost on restart"],
            ["Filesystem — users/<session>/", "Per session",
             "Raw uploaded files, extracted content.txt, imp_sents.txt (summary), metadata.json.",
             "Persistent"],
        ],
        col_widths=[Inches(1.5), Inches(1.7), Inches(2.6), Inches(0.85)])
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # §5 SUBSYSTEM INTERFACE AND DEPENDENCIES
    # ─────────────────────────────────────────────────────────────────────────
    _heading(doc, "Subsystem interface and dependencies", 1)
    doc.add_paragraph()

    _heading(doc, "External interfaces and messages", 2)
    doc.add_paragraph()
    _body(doc, "Table 5-1: External interfaces")
    doc.add_paragraph()
    _plain_table(doc,
        ["#", "External Interface", "Format / Protocol", "Remarks"],
        [
            ["1", "Client Applications\n(Frontend / WhatsApp / Mobile)",
             "HTTP/HTTPS REST\nJSON; multipart/form-data for uploads",
             "JWT required for authenticated endpoints. Trial uses browser fingerprint."],
            ["2", "C-DOT GPU Server (LLM)",
             "HTTPS POST to /cdot/ollama2/api/chat\n(OpenAI-compatible chat format)",
             "API key in Authorization header. SSL verification configurable. Timeout 120 s."],
            ["3", "Ollama Server (Embeddings)",
             "HTTP — OllamaEmbeddings (LangChain)",
             "Used at ingestion only. Model: bge-m3:latest. Must be accessible from backend host."],
            ["4", "vexyl-tts\n(indic-parler-tts)",
             "WebSocket — streams WAV audio chunks",
             "On-premise. URL: VEXYL_TTS_URL. 23 Indian languages. Used by /api/ask-tts."],
            ["5", "vexyl-stt\n(indic-conformer + distil-whisper)",
             "WebSocket — streams partial + final transcripts",
             "On-premise. URL: VEXYL_STT_URL. Auto language detection via Vakgyata LID."],
            ["6", "IndicTrans2 Server\n(Translation)",
             "HTTP POST {text, target_language}",
             "Falls back to English on failure. 22 Indian languages supported."],
            ["7", "Gemma 4 Server\n(Image Captioning)",
             "HTTP POST with base64 image",
             "Caption injected into document context when image attached to query."],
        ],
        col_widths=[Inches(0.3), Inches(1.4), Inches(1.9), Inches(3.0)])

    _heading(doc, "Internal interfaces", 2)
    doc.add_paragraph()
    _body(doc,
        "All internal communication is in-process Python method calls via get_*_service() "
        "singleton factory functions. Key call chains:"
    )
    for chain in [
        "queries_bp (FastAPI router)  →  QueryService.process_authenticated_query()  →  QueryAgentService.process_query()",
        "QueryAgentService  →  QueryIntentService.classify_intent()  →  ContextProviderService.get_document_context()  →  ResponseGeneratorService.generate_document_response()",
        "QueryAgentService  →  CreativeReasoningService.process_creative_query_stream()  →  AdaptiveSearchService  →  ResultEvaluationService",
        "documents_bp  →  DocumentService.process_files_and_urls()  →  upload.py.store_vector()  →  ElasticDocumentManager.add_documents()",
        "ChatHistoryManager  ↔  MongoDB (chat_sessions, chat_names) via Beanie ODM",
    ]:
        _bullet(doc, chain)
    doc.add_paragraph()

    _heading(doc, "Hardware interfaces", 2)
    doc.add_paragraph()
    _plain_table(doc,
        ["Component", "Hardware Interface", "Notes"],
        [
            ["C-DOT GPU Server", "NVIDIA GPU cluster (HTTPS)", "70B LLM inference. Recommended: 2× A100 80 GB."],
            ["Elasticsearch",    "Cloud or bare-metal cluster", "HTTP/HTTPS on port 9200."],
            ["MongoDB",          "Cloud or bare-metal", "Default port 27017."],
            ["Ollama",           "Local GPU or CPU host", "Port configurable via OLLAMA_BASE_URL."],
            ["vexyl-tts / vexyl-stt", "Local GPU host (WebSocket)", "WebSocket servers on-premise. GPU accelerates inference."],
            ["ChromeDriver",     "Local CPU — headless Chrome", "Required for dynamic web page scraping via Selenium."],
        ],
        col_widths=[Inches(1.5), Inches(2.0), Inches(3.1)])

    _heading(doc, "User interfaces", 2)
    doc.add_paragraph()
    _body(doc,
        "This subsystem does not expose a direct graphical user interface. All user interaction "
        "is mediated through client applications (web app, WhatsApp bot, mobile) consuming the "
        "REST API. The API exposes auto-generated documentation at /docs (Swagger UI) and "
        "/redoc (ReDoc). Refer to the Sachet Frontend and API Documentation for UI-level details."
    )
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # ANNEXURE A: CHUNKING STRATEGY
    # ─────────────────────────────────────────────────────────────────────────
    _heading(doc, "Annexure A: Chunking Strategy Details", 1)
    doc.add_paragraph()
    _body(doc, "Text chunking is performed in controllers/upload.py via a two-stage pipeline.")
    doc.add_paragraph()

    _heading(doc, "Stage 1 — Markdown Header Splitting", 2)
    doc.add_paragraph()
    _body(doc,
        "MarkdownHeaderTextSplitter (LangChain) splits extracted text on heading markers "
        "(#, ##, ###). This preserves logical document structure so chunks respect section "
        "boundaries. Header text is propagated into chunk metadata for context attribution."
    )
    doc.add_paragraph()

    _heading(doc, "Stage 2 — Recursive Character Splitting", 2)
    doc.add_paragraph()
    _plain_table(doc,
        ["Parameter", "Value", "Rationale"],
        [
            ["chunk_size",    "1500 characters",
             "Fits within LLM context while carrying sufficient information per chunk."],
            ["chunk_overlap", "300 characters (20%)",
             "Prevents loss of context at boundaries; 20% overlap is standard RAG practice."],
            ["Separators",    r"['\n\n', '\n', '. ', ' ', '']",
             "Hierarchical: paragraph → sentence → word → character split."],
        ],
        col_widths=[Inches(1.5), Inches(1.8), Inches(3.3)])
    _body(doc,
        "Each chunk carries metadata: source, filename, page, content_type (text/table), "
        "table_id. Table chunks receive special handling — when a table chunk appears in "
        "top-k, all chunks for that table_id are fetched to avoid partial table answers."
    )
    doc.add_paragraph()

    _heading(doc, "NuMarkdown Enhancement (numarkdown branch — pending merge)", 2)
    doc.add_paragraph()
    _body(doc,
        "The numarkdown branch improves chunking with NuExtract3-based extraction and "
        "hierarchical header breadcrumbs. Each chunk will carry a full header path "
        "(e.g., 'Chapter 2 > Section 3 > Sub-section 1') enabling better context attribution."
    )
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # ANNEXURE B: SCALABILITY CONSIDERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    _heading(doc, "Annexure B: Scalability Considerations", 1)
    doc.add_paragraph()
    _plain_table(doc,
        ["Layer", "Scalability Mechanism", "Current Limit / Notes"],
        [
            ["FastAPI / Uvicorn Workers",
             "Async stateless design — horizontally scalable behind Nginx + Uvicorn. "
             "Each worker holds its own singleton service instances.",
             "Tested 100+ concurrent users. Workers = CPU cores × 2 + 1 recommended."],
            ["Elasticsearch",
             "Horizontal scaling via shard replication. Separate index per knowledge "
             "container enables per-tenant isolation.",
             "Scales to TB-level. Vector dimension fixed at 1024 (bge-m3)."],
            ["MongoDB",
             "Replica sets for HA; sharding for large deployments. Chat history "
             "can be time-partitioned per user_session.",
             "Current: single instance. Production: 3-node replica set minimum."],
            ["LLM GPU Server",
             "Centralised C-DOT GPU server. Multiple GPU nodes behind load balancer "
             "for high-concurrency production deployments.",
             "Single GPU node = single point of failure. HA requires secondary node."],
            ["Embedding (Ollama)",
             "Ollama scalable to multiple instances; OLLAMA_BASE_URL can point to "
             "a load-balanced cluster.",
             "Embedding is ingestion-time only — not on query critical path."],
            ["Rate Limiting",
             "Slowapi with Redis backend (recommended for multi-worker). "
             "Per-endpoint and per-user limits enforced.",
             "Default: in-memory per worker. Multi-worker: Redis backend required."],
            ["File Storage",
             "Local filesystem (users/). Multi-host: NFS or S3/MinIO object storage.",
             "Current: local disk. Multi-node production: shared storage required."],
        ],
        col_widths=[Inches(1.4), Inches(3.0), Inches(2.2)])
    _body(doc,
        "Recommended production topology: 2× FastAPI/Uvicorn workers behind Nginx → "
        "3-node Elasticsearch cluster → MongoDB replica set → Redis (rate limit state) → "
        "C-DOT GPU server cluster (2+ nodes) → Ollama on dedicated GPU host."
    )
    doc.add_page_break()

    # ─────────────────────────────────────────────────────────────────────────
    # ANNEXURE C: BRANCH ROADMAP
    # ─────────────────────────────────────────────────────────────────────────
    _heading(doc, "Annexure C: Branch Roadmap — Features Pending Merge", 1)
    doc.add_paragraph()
    _body(doc,
        "The following features are under active development in separate git branches "
        "and are planned for merging into the main codebase."
    )
    doc.add_paragraph()

    _heading(doc, "C.1  FastAPI Migration  (release/fastapi-migration — merged into main)", 2)
    doc.add_paragraph()
    _plain_table(doc,
        ["Aspect", "Flask (legacy)", "FastAPI (current)"],
        [
            ["Framework",       "Flask 2.3",                "FastAPI + Starlette"],
            ["Rate Limiting",   "Flask-Limiter",            "Slowapi"],
            ["Request Schemas", "Manual dict parsing",      "Pydantic v2 (app/schemas/)"],
            ["Auth",            "Manual JWT in route",      "Dependency injection (deps.py get_current_user)"],
            ["MongoDB ODM",     "PyMongo direct",           "Beanie ODM + AsyncIOMotorClient (async)"],
            ["API Docs",        "None",                     "Swagger UI at /docs; ReDoc at /redoc"],
            ["Streaming",       "flask.Response + generator","FastAPI StreamingResponse"],
            ["App Entry",       "run.py (Flask app.run)",   "main.py (uvicorn / lifespan context)"],
        ],
        col_widths=[Inches(1.4), Inches(2.2), Inches(3.0)])
    doc.add_paragraph()

    _heading(doc, "C.2  Docling Ingestion Pipeline + Gemma 4 Vision  (gemma4)", 2)
    doc.add_paragraph()
    for item in [
        "Docling Pipeline (app/services/docling_pipeline.py): Layout-aware PDF parsing preserving table structure, headings, and page layout. Replaces PyMuPDF text extraction.",
        "Gemma 4 Vision Captioning: Images/charts extracted from PDFs sent to C-DOT GPU server running Gemma 4. Caption stored with chunk, enabling image-aware retrieval.",
        "Image Chat History: Images uploaded with queries stored in chat_images/ and served via /chat_images/<path>. Image URLs persisted in chat history metadata.",
        "Architectural impact: Standalone ingestion package for batch processing; MySQL schema for enterprise RAG (document_chunks, image_chunks, table_data).",
    ]:
        _bullet(doc, item)
    doc.add_paragraph()

    _heading(doc, "C.3  NuMarkdown Chunking  (numarkdown)", 2)
    doc.add_paragraph()
    for item in [
        "NuExtract3 Integration: Structured extraction before chunking — improves handling of tables, lists, and formatted content.",
        "Hierarchical Chunks: Each chunk carries full header breadcrumb (e.g., 'Chapter 2 > Section 3'), enabling precise context attribution in LLM responses.",
        "Architectural impact: Backwards-compatible change to upload.py; chunk metadata schema extended with 'header' field.",
    ]:
        _bullet(doc, item)
    doc.add_paragraph()

    _heading(doc, "C.4  STT / TTS via Vexyl  (stt-tts — current development branch)", 2)
    doc.add_paragraph()
    _plain_table(doc,
        ["Service", "Model", "Server", "Protocol", "Languages"],
        [
            ["TTS", "ai4bharat/indic-parler-tts", "vexyl-tts", "WebSocket — WAV chunks", "23 Indian languages"],
            ["STT (Indic)", "ai4bharat/indic-conformer-600m-multilingual", "vexyl-stt", "WebSocket — partial + final", "22 Indian languages"],
            ["STT (English)", "distil-whisper/distil-medium.en", "vexyl-stt", "WebSocket", "English"],
            ["Lang ID", "onecxi/vakgyata-base", "vexyl-stt", "Auto detection", "All supported"],
        ],
        col_widths=[Inches(0.8), Inches(2.1), Inches(0.9), Inches(1.6), Inches(1.2)])
    doc.add_paragraph()

    _heading(doc, "C.5  MongoDB Knowledge Base  (feature/mongodb-kb-integration)", 2)
    doc.add_paragraph()
    for item in [
        "NL→MongoDB Query Translation (controllers/mongodb_db.py): LLM translates natural language into PyMongo query JSON against the disaster_alerts.alerts collection.",
        "Alerts Schema: StateList, DistrictList, disaster_type, severity (ALERT/WARNING/WATCH), certainty, effective_start_time, effective_end_time, warning_message, centroidPoint (GeoJSON).",
        "Intent Routing: New intent type for MongoDB KB queries — disaster alert queries routed to MongoDB context provider instead of Elasticsearch.",
        "Architectural impact: New context provider path alongside existing Elasticsearch + SQLite paths.",
    ]:
        _bullet(doc, item)
    doc.add_paragraph()

    _plain_table(doc,
        ["Branch", "Feature", "Merge Status", "Architectural Impact"],
        [
            ["release/fastapi-migration", "Flask → FastAPI, Pydantic, Beanie ODM",
             "Merged into main", "High — framework change"],
            ["gemma4", "Docling pipeline, Gemma 4 vision captioning",
             "Pending merge", "Medium — new ingestion path"],
            ["numarkdown", "NuExtract3, hierarchical header chunking",
             "Pending merge", "Low — backwards-compatible"],
            ["stt-tts", "vexyl-tts (indic-parler-tts), vexyl-stt (indic-conformer)",
             "Pending merge", "Medium — replaces cloud TTS/STT"],
            ["feature/mongodb-kb-integration", "NL→MongoDB for disaster alerts KB",
             "Pending merge", "Medium — new context provider"],
        ],
        col_widths=[Inches(1.8), Inches(2.4), Inches(1.1), Inches(1.3)])

    doc.add_paragraph()
    _body(doc, "\n[ END OF DOCUMENT ]")

    doc.save(OUT_DOCX)
    print(f"Saved → {OUT_DOCX}")


if __name__ == "__main__":
    build_document()
