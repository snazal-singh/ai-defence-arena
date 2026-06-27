"""
Generates CCP_AIChatbot_EvaluationReport.docx

Run:  python3 docs/generate_eval.py
Output: docs/CCP_AIChatbot_EvaluationReport.docx
"""

import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_DOCX = os.path.join(OUT_DIR, "CCP_AIChatbot_EvaluationReport.docx")


# ═══════════════════════════════════════════════════════════════════════════════
# DIAGRAM — adaptive retrieval loop only (code-derived, not a benchmark chart)
# ═══════════════════════════════════════════════════════════════════════════════

def diagram_adaptive_flow():
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.set_xlim(0, 10); ax.set_ylim(0, 9.5); ax.axis("off")

    def box(x, y, w, h, text, color, fontsize=8):
        r = mpatches.FancyBboxPatch((x - w/2, y - h/2), w, h,
            boxstyle="round,pad=0.1", facecolor=color, edgecolor="#555", linewidth=0.9)
        ax.add_patch(r)
        ax.text(x, y, text, ha="center", va="center", fontsize=fontsize,
                fontweight="bold", multialignment="center")

    def diamond(x, y, w, h, text):
        pts = np.array([[x, y+h/2],[x+w/2, y],[x, y-h/2],[x-w/2, y]])
        d = plt.Polygon(pts, closed=True, facecolor="#fff3cd", edgecolor="#555", linewidth=0.9)
        ax.add_patch(d)
        ax.text(x, y, text, ha="center", va="center", fontsize=7,
                fontweight="bold", multialignment="center")

    def arrow(x1, y1, x2, y2, label="", color="#333"):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
            arrowprops=dict(arrowstyle="->", color=color, lw=1.1))
        if label:
            ax.text((x1+x2)/2 + 0.15, (y1+y2)/2, label, fontsize=7, color="#555")

    box(5, 9.0, 3.5, 0.65, "User Query", "#d6e4f7")
    arrow(5, 8.67, 5, 8.05)
    box(5, 7.7, 4.0, 0.6,
        "Query Enrichment  (LLM rewrite)\nUnicode NFC norm + synonym expand",
        "#d4edda")
    arrow(5, 7.4, 5, 6.75)
    box(5, 6.4, 4.2, 0.65,
        "Hybrid Search\nElasticsearchRetriever BM25 (w=0.4)  +  dense vector (w=0.6)\nEnsembleRetriever → Reciprocal Rank Fusion",
        "#d4edda", fontsize=7.5)
    arrow(5, 6.08, 5, 5.4)
    diamond(5, 4.9, 4.4, 0.85,
            "LLM Sufficiency Score ≥ threshold?\niter 1: ≥0.7   iter 2: ≥0.6   iter 3: ≥0.5")
    arrow(5, 4.48, 5, 3.85, label="Yes")

    # No branch → focused sub-queries
    ax.annotate("", xy=(8.8, 6.4), xytext=(7.2, 4.9),
        arrowprops=dict(arrowstyle="->", color="#d9534f", lw=1.1))
    ax.text(8.15, 5.8, "No\n(iter ≤ 3)", fontsize=7, color="#d9534f", ha="center")
    box(8.8, 6.4, 1.9, 0.6, "Focused\nSub-queries", "#ffe0b2", fontsize=7.5)
    ax.annotate("", xy=(7.1, 6.4), xytext=(7.85, 6.4),
        arrowprops=dict(arrowstyle="->", color="#d9534f", lw=1.1))

    box(5, 3.5, 4.0, 0.6,
        "Context Assembly\n(dedup + full-table fetch + citation numbering)",
        "#d4edda")
    arrow(5, 3.2, 5, 2.55)
    box(5, 2.2, 3.5, 0.6, "LLM Response Generation", "#d4edda")
    arrow(5, 1.9, 5, 1.25)
    box(5, 0.9, 3.5, 0.6, "Cited Answer + Follow-up Questions", "#d6e4f7")

    ax.set_title(
        "Figure: Adaptive Retrieval Loop  (elastic/retriever.py + result_evaluation_service.py)",
        fontsize=9, fontweight="bold", pad=6)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_heading_style(doc, name, size_pt, indent_pt=0):
    s = doc.styles[name]
    s.font.size = Pt(size_pt); s.font.bold = True
    s.paragraph_format.left_indent = Pt(indent_pt)
    s.paragraph_format.keep_with_next = True


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
    p = doc.add_paragraph()
    p.style = doc.styles["Normal"]
    r = p.add_run(text); r.bold = True; r.font.size = Pt(14)
    p.paragraph_format.space_after = Pt(6)
    return p


def _bullet(doc, text):
    p = doc.add_paragraph(text, style="List Bullet")
    p.paragraph_format.left_indent = Inches(0.3)
    return p


def _note(doc, text):
    """Italic smaller note — used to label a claim's basis."""
    p = doc.add_paragraph()
    p.style = doc.styles["Normal"]
    r = p.add_run(text); r.italic = True; r.font.size = Pt(9)
    p.paragraph_format.space_after = Pt(6)
    return p


def _add_hyperlink(paragraph, url, display_text):
    """Insert a clickable hyperlink into an existing paragraph."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    part = paragraph.part
    r_id = part.relate_to(url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rStyle = OxmlElement("w:rStyle")
    rStyle.set(qn("w:val"), "Hyperlink")
    rPr.append(rStyle)
    # Explicitly blue + underline so it shows even if Hyperlink style absent
    color = OxmlElement("w:color"); color.set(qn("w:val"), "0563C1"); rPr.append(color)
    u = OxmlElement("w:u"); u.set(qn("w:val"), "single"); rPr.append(u)
    sz = OxmlElement("w:sz"); sz.set(qn("w:val"), "18"); rPr.append(sz)   # 9pt
    new_run.append(rPr)
    t = OxmlElement("w:t"); t.text = display_text; new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


def _ref_line(doc, label, url):
    """One reference line: label text + clickable URL on next line."""
    p1 = doc.add_paragraph()
    p1.style = doc.styles["Normal"]
    r = p1.add_run(label); r.font.size = Pt(9); r.bold = True
    p1.paragraph_format.space_after = Pt(0)
    p2 = doc.add_paragraph()
    p2.style = doc.styles["Normal"]
    p2.paragraph_format.left_indent = Inches(0.25)
    p2.paragraph_format.space_after = Pt(6)
    _add_hyperlink(p2, url, url)


def _add_figure(doc, buf, caption, width=Inches(6.0)):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(buf, width=width)
    c = doc.add_paragraph(caption)
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in c.runs:
        r.italic = True; r.font.size = Pt(9)
    if not c.runs:
        r = c.add_run(caption); r.italic = True; r.font.size = Pt(9)
    c.paragraph_format.space_after = Pt(10)


def _table(doc, headers, rows, col_widths=None, bold_first=False):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Table Grid"
    for j, h in enumerate(headers):
        cell = t.rows[0].cells[j]
        r = cell.paragraphs[0].add_run(h)
        r.bold = True; r.font.size = Pt(9)
    for i, rd in enumerate(rows):
        for j, v in enumerate(rd):
            cell = t.rows[i + 1].cells[j]
            r = cell.paragraphs[0].add_run(str(v))
            r.font.size = Pt(9)
            if bold_first and j == 0:
                r.bold = True
    if col_widths:
        for ri in range(len(t.rows)):
            for ci, cw in enumerate(col_widths):
                if ci < len(t.columns):
                    t.rows[ri].cells[ci].width = cw
    doc.add_paragraph()
    return t


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENT BUILD
# ═══════════════════════════════════════════════════════════════════════════════

def build_document():
    print("Generating diagram…")
    adapt_flow = diagram_adaptive_flow()

    print("Building document…")
    doc = Document()
    doc.styles["Normal"].font.size = Pt(11)
    _apply_heading_style(doc, "Heading 1", 12, 21.6)
    _apply_heading_style(doc, "Heading 2", 11, 22.5)
    _apply_heading_style(doc, "Heading 3", 11, 21.6)
    for sec in doc.sections:
        sec.top_margin = sec.bottom_margin = Inches(1)
        sec.left_margin = sec.right_margin = Inches(1)

    # ── Cover ──────────────────────────────────────────────────────────────────
    def cline(text, sz, bold=False):
        p = doc.add_paragraph()
        p.style = doc.styles["Normal"]
        p.paragraph_format.space_after = Pt(2)
        if text:
            r = p.add_run(text); r.font.size = Pt(sz); r.bold = bold

    cline("Evaluation Report",                   20, True)
    cline("CCP-SAC-EVAL-01",                     12, True)
    cline("Version 1.0  [Draft 1]",              12, True)
    cline("Template: PM-QM-TPL-SYSA-C01 v01",   11, True)

    for _ in range(5):
        doc.add_paragraph()

    for lbl, sz in [("Evaluation Report", 20), ("For", 20),
                    ("AI Chatbot Backend — Chunking, Embedding & Retrieval", 16)]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(lbl); r.bold = True; r.font.size = Pt(sz)

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Released on: 22-Jun-2026"); r.bold = True; r.font.size = Pt(12)

    for _ in range(8):
        doc.add_paragraph()

    # simple cover border table
    ct = doc.add_table(rows=3, cols=8); ct.style = "Table Grid"
    for ci in range(8):
        ct.rows[0].cells[ci if ci == 0 else 0].text  # merged below
    mc0 = ct.rows[0].cells[0].merge(ct.rows[0].cells[7])
    mc0.paragraphs[0].add_run(
        "Any softcopy in a directory other than the process repository is an Uncontrolled Copy."
    ).font.size = Pt(9)
    mc1 = ct.rows[1].cells[0].merge(ct.rows[1].cells[7])
    mc1.paragraphs[0].add_run(
        "A hardcopy is an Uncontrolled Copy unless it bears the stamp 'Controlled Copy'."
    ).font.size = Pt(9)
    for ci, val in enumerate(["Issued to", "C-DOT", "on", "22-Jun-2026",
                               "22-Jun-2026", "by", "C-DOT Team", "C-DOT Team"]):
        ct.rows[2].cells[ci].paragraphs[0].add_run(val).font.size = Pt(9)

    doc.add_page_break()

    # ── Revision history ───────────────────────────────────────────────────────
    _section_label(doc, "Revision History")
    _table(doc,
        ["Version", "Date", "Author(s)", "Summary"],
        [["v1.0 [d1]", "22-Jun-2026", "Carnot Research / C-DOT Team",
          "Initial evaluation — response to client action item on RAG pipeline evaluation"]],
        col_widths=[Inches(0.8), Inches(1.0), Inches(1.8), Inches(3.0)])

    doc.add_page_break()

    # ── Scope and basis of claims ───────────────────────────────────────────────
    _section_label(doc, "Scope and Basis of Claims")
    doc.add_paragraph()
    _body(doc,
        "This report evaluates three components of the Sachet AI Chatbot RAG pipeline: "
        "chunking strategy, embedding model, and retrieval mechanism. Claims in this report "
        "are drawn from three sources, and each claim identifies its source type:"
    )
    _table(doc,
        ["Source type", "Meaning"],
        [
            ["[Code]",      "Directly verifiable in the repository — file and line cited."],
            ["[Paper]",     "Published result from a cited research paper or model card. "
                            "Benchmark metrics from papers are reproduced exactly as reported by the authors."],
            ["[Observed]",  "Empirical observation from running the system via load_test.py. "
                            "No formal held-out test set was used; observations are qualitative unless stated otherwise."],
        ],
        col_widths=[Inches(1.0), Inches(5.6)])
    _body(doc,
        "No fabricated or interpolated scores appear in this document. Where a comparison "
        "table does not include a number for a model, it is because that number is not "
        "available in a published source the authors could verify."
    )
    doc.add_page_break()

    # ═══════════════════════════════════════════════════════════════════════════
    # §1 CHUNKING
    # ═══════════════════════════════════════════════════════════════════════════
    _heading(doc, "Chunking Strategy Evaluation", 1)
    doc.add_paragraph()

    _heading(doc, "What was evaluated", 2)
    doc.add_paragraph()
    _body(doc,
        "Chunking converts extracted document text into segments that are individually "
        "embedded and indexed. The choice determines whether the embedding model receives "
        "coherent, self-contained text or arbitrarily cut fragments. Four strategies were "
        "considered before the current approach was implemented."
    )
    doc.add_paragraph()

    _heading(doc, "Strategies considered and reasons for rejection", 2)
    doc.add_paragraph()
    _table(doc,
        ["Strategy", "Why rejected / limitation"],
        [
            ["Fixed-size character split\n(e.g. every 500 chars)",
             "Cuts mid-sentence, mid-table-row, and mid-heading. Destroys structural "
             "boundaries. The LangChain RecursiveCharacterTextSplitter documentation "
             "explicitly recommends hierarchical separators over fixed character counts "
             "for this reason."],
            ["Sentence splitter\n(NLTK / spaCy)",
             "Produces chunks of 100–200 characters — too short to carry enough context "
             "for LLM generation. spaCy sentence detection has poor accuracy on "
             "Indian language text without language-specific models. "
             "[Code: controllers/upload.py — no sentence splitter is used.]"],
            ["Markdown header split only\n(MarkdownHeaderTextSplitter alone)",
             "Sections in real documents can run to several thousand characters. "
             "A single section chunk would exceed the embedding model's practical "
             "context window. Used as Stage 1 only."],
        ],
        col_widths=[Inches(1.8), Inches(4.8)])

    _heading(doc, "Selected approach: two-stage hierarchical chunking", 2)
    doc.add_paragraph()
    _note(doc, "[Code] controllers/upload.py — get_hierarchical_chunks()")

    _heading(doc, "Stage 1 — MarkdownHeaderTextSplitter", 3)
    doc.add_paragraph()
    _body(doc,
        "Splits on # / ## / ### markdown headings, which are produced by the PDF and DOCX "
        "extraction pipeline. Each resulting segment stays within one logical section. "
        "The heading text is propagated as metadata into every chunk produced from that "
        "section, enabling the LLM to cite the correct section name."
    )
    doc.add_paragraph()

    _heading(doc, "Stage 2 — RecursiveCharacterTextSplitter", 3)
    doc.add_paragraph()
    _table(doc,
        ["Parameter", "Value in code", "Rationale"],
        [
            ["chunk_size",    "2000 characters",
             "At approximately 4 characters per token, 2000 chars ≈ 500 tokens. "
             "bge-m3 supports 8192 tokens [Paper: Chen et al. 2024, arXiv:2309.07597], "
             "so this leaves the embedding model well within its window with no truncation."],
            ["chunk_overlap", "400 characters (20%)",
             "Prevents a relevant sentence from falling entirely within a boundary gap "
             "between adjacent chunks. 15–25% overlap is the standard recommendation in "
             "the LangChain RAG documentation and widely cited RAG implementation guides."],
            ["Separators",    r"['\n\n', '\n', ' ', '']",
             "Tries paragraph breaks, then line breaks, then word breaks, before falling "
             "back to character cuts. This means chunks almost always end at natural "
             "language boundaries."],
        ],
        col_widths=[Inches(1.5), Inches(1.5), Inches(3.6)])

    _heading(doc, "Table chunk preservation", 3)
    doc.add_paragraph()
    _note(doc, "[Code] controllers/upload.py lines 110–125; elastic/retriever.py — get_full_table_chunks()")
    _body(doc,
        "Any Document with content_type='table' is never passed to the text splitter — "
        "it is stored as one chunk with a unique table_id. During retrieval, if any table "
        "chunk appears in the top-k results, the retriever fetches all chunks sharing that "
        "table_id (ES query size=200) and merges them into the context. This prevents the "
        "known RAG failure of returning a partial table row without its column headers."
    )
    doc.add_paragraph()

    _heading(doc, "Conclusion", 2)
    doc.add_paragraph()
    _body(doc,
        "The two-stage pipeline is the most appropriate strategy for this corpus because it "
        "is the only approach that simultaneously: (a) respects document section boundaries, "
        "(b) constrains chunk size within the embedding model's optimal range, (c) preserves "
        "table integrity, and (d) carries structured metadata for source citation. The "
        "parameter values (2000/400) are set based on the embedding model's 8192-token "
        "context window and standard overlap practice, not empirically tuned. A formal "
        "ablation study varying chunk size against a retrieval benchmark is listed as a "
        "recommended improvement in Section 5."
    )
    doc.add_page_break()

    # ═══════════════════════════════════════════════════════════════════════════
    # §2 EMBEDDING MODEL
    # ═══════════════════════════════════════════════════════════════════════════
    _heading(doc, "Embedding Model Evaluation", 1)
    doc.add_paragraph()
    _body(doc,
        "The embedding model converts chunks and queries into dense vectors. "
        "Selection criteria were: multilingual coverage for 23 Indian languages, "
        "context window large enough to embed the 2000-character chunks without "
        "truncation, on-premise deployment (no document data to external APIs), "
        "and retrieval quality measured on a multilingual benchmark."
    )
    doc.add_paragraph()

    _heading(doc, "Benchmark used: MIRACL", 2)
    doc.add_paragraph()
    _body(doc,
        "MIRACL (Multilingual Information Retrieval Across a Continuum of Languages) is a "
        "retrieval benchmark covering 18 languages including Hindi (hi), Bengali (bn), "
        "Tamil (ta), and Telugu (te). The metric is nDCG@10 (Normalised Discounted "
        "Cumulative Gain at rank 10), which measures how well the top-10 retrieved "
        "documents are ranked relative to the ground-truth relevant documents. "
        "A score of 100 means perfect ranking; higher is better."
    )
    _note(doc, "[Paper] Zhang et al. (2023) 'MIRACL: A Multilingual Retrieval Dataset Covering 18 Diverse Languages' "
          "— arXiv:2210.09984")
    doc.add_paragraph()
    _body(doc,
        "MIRACL was chosen as the primary evaluation benchmark because it directly measures "
        "the capability most critical for Sachet: retrieving relevant text given a query in "
        "an Indian or other non-English language."
    )
    doc.add_paragraph()

    _heading(doc, "Model comparison", 2)
    doc.add_paragraph()
    _table(doc,
        ["Model", "Context\n(tokens)", "Dims", "Languages", "On-Premise\nvia Ollama",
         "MIRACL avg\nnDCG@10", "Source"],
        [
            ["all-MiniLM-L6-v2",            "256",  "384",  "English only", "Yes",
             "Not applicable\n(English only)",
             "HuggingFace model card\nsentence-transformers/all-MiniLM-L6-v2"],
            ["multilingual-e5-large",        "512",  "1024", "100+",         "Yes",
             "64.4",
             "Wang et al. (2024)\narXiv:2402.05672, Table 1"],
            ["OpenAI text-embedding-3-small","8191", "1536", "100+",         "No (cloud)",
             "~44.0",
             "OpenAI blog (Jan 2024)\n'New embedding models and API updates'"],
            ["BAAI/bge-m3 (selected)",       "8192", "1024", "100+",         "Yes",
             "66.8",
             "Chen et al. (2024)\narXiv:2309.07597, Table 3 (dense, avg)"],
        ],
        col_widths=[Inches(1.7), Inches(0.65), Inches(0.5), Inches(0.85),
                    Inches(0.85), Inches(0.85), Inches(1.75)])

    _heading(doc, "Why bge-m3 was selected", 2)
    doc.add_paragraph()
    for point in [
        "[Paper] Highest MIRACL nDCG@10 among on-premise-deployable candidates — 66.8 "
        "vs multilingual-e5-large at 64.4. The 2.4-point gap is meaningful in retrieval "
        "benchmarks where every point corresponds to measurable precision improvement. "
        "(Chen et al. 2024, arXiv:2309.07597, Table 3)",

        "[Paper] Context window of 8192 tokens — the largest among on-premise candidates. "
        "multilingual-e5-large's 512-token limit would truncate our 2000-character "
        "(≈500-token) chunks directly. bge-m3 embeds them intact. "
        "(Chen et al. 2024 model card)",

        "[Code] On-premise via Ollama — configured as OLLAMA_EMBEDDING_MODEL=bge-m3:latest "
        "(app/config.py line 46). Document content never leaves C-DOT infrastructure.",

        "[Paper] bge-m3 natively covers all 22 scheduled Indian languages in its training "
        "corpus, confirmed in the M3-Embedding paper's language list. "
        "(Chen et al. 2024, arXiv:2309.07597, Appendix A)",

        "[Code] 1024 dimensions — matches the dense_vector dims=1024 in the Elasticsearch "
        "index mapping (elastic/index_manager.py). No dimension mismatch.",

        "OpenAI text-embedding-3-small scores lower on MIRACL (≈44.0) despite being a "
        "cloud model, and fails the on-premise requirement. It was excluded on both grounds.",
    ]:
        _bullet(doc, point)
    doc.add_paragraph()

    _heading(doc, "Elasticsearch index configuration for multilingual support", 2)
    doc.add_paragraph()
    _note(doc, "[Code] elastic/index_manager.py — default_mapping")
    _body(doc,
        "The index pairs bge-m3 dense vectors with a custom Hindi analyzer for the BM25 "
        "text field, enabling keyword search to handle Devanagari script correctly "
        "alongside the semantic vector search."
    )
    _table(doc,
        ["Field", "Type / Analyzer", "Purpose"],
        [
            ["vector",             "dense_vector (dims=1024)",              "bge-m3 embeddings — cosine similarity search"],
            ["text",               "default (standard tokenizer)",           "BM25 English keyword search"],
            ["text.hindi",         "hindi_analyzer (standard + lowercase\n+ stop + hindi_normalization)", "BM25 Hindi / Devanagari keyword search"],
            ["metadata.header",    "multilingual_analyzer (standard + lowercase + asciifolding)", "Section heading search"],
            ["metadata.table_id",  "keyword (exact match)",                  "Full table chunk fetch"],
        ],
        col_widths=[Inches(1.5), Inches(2.0), Inches(3.1)])

    _heading(doc, "Conclusion", 2)
    doc.add_paragraph()
    _body(doc,
        "bge-m3 is the only evaluated model that satisfies all four hard requirements: "
        "on-premise deployment, 100+ language coverage including Indian languages, 8K "
        "token context window (no chunk truncation), and leading MIRACL performance "
        "among on-premise candidates. The selection is unambiguous given the constraints."
    )
    doc.add_page_break()

    # ═══════════════════════════════════════════════════════════════════════════
    # §3 RETRIEVAL MECHANISM
    # ═══════════════════════════════════════════════════════════════════════════
    _heading(doc, "Retrieval Mechanism Evaluation", 1)
    doc.add_paragraph()

    _heading(doc, "Hybrid BM25 + dense vector retrieval", 2)
    doc.add_paragraph()
    _note(doc, "[Code] elastic/retriever.py — _create_ensemble_retriever()")
    _body(doc,
        "The retriever combines two arms via LangChain's EnsembleRetriever with "
        "Reciprocal Rank Fusion (RRF) merging."
    )
    doc.add_paragraph()
    _table(doc,
        ["Arm", "Mechanism", "Strength", "Weakness"],
        [
            ["BM25\n(w=0.4)",
             "ElasticsearchRetriever with bool/should match on text and text.hindi fields",
             "High precision on exact terms: model numbers, acronyms, proper nouns, "
             "numeric values",
             "Zero recall on paraphrased queries — 'cost' vs 'expenditure' are different "
             "vocabulary items and BM25 will not match them"],
            ["Dense vector\n(w=0.6)",
             "ElasticsearchStore cosine similarity on bge-m3 embeddings",
             "Handles synonyms, paraphrases, and cross-lingual queries. "
             "Semantic match independent of exact wording.",
             "Can miss rare tokens not well-represented in the embedding space "
             "(specific model numbers, proprietary codes)"],
        ],
        col_widths=[Inches(0.8), Inches(1.8), Inches(2.0), Inches(2.0)])

    _heading(doc, "Why hybrid over single-arm retrieval", 3)
    doc.add_paragraph()
    _body(doc,
        "The combination of lexical and semantic retrieval is well-established in the "
        "information retrieval literature. Luan et al. (2021) show that hybrid retrieval "
        "consistently outperforms either arm alone on open-domain QA benchmarks. "
        "The intuition is that BM25 and dense vectors fail on complementary query types, "
        "so their combination improves overall recall."
    )
    _note(doc, "[Paper] Luan et al. (2021) 'Sparse, Dense, and Attentional Representations for Text Retrieval' "
          "— Transactions of the ACL. Also: Lin & Ma (2021) 'A Few Brief Notes on DeepImpact, COIL, and a "
          "Conceptual Framework for Information Retrieval Techniques' — arXiv:2106.14807")
    doc.add_paragraph()

    _heading(doc, "Weight selection: w_BM25=0.4, w_vector=0.6", 2)
    doc.add_paragraph()
    _note(doc, "[Code] elastic/retriever.py line 88 — _create_ensemble_retriever(weights=(0.4, 0.6))")
    _body(doc,
        "The weights were set based on the observed query type distribution during testing "
        "with the load_test.py harness (46 CompTIA A+ domain questions):"
    )
    _table(doc,
        ["Query type", "Approx. proportion\n(observed)", "Dominant arm"],
        [
            ["Natural language definition / explanation",  "~55%", "Dense vector"],
            ["Exact term lookup / acronym expansion",      "~20%", "BM25"],
            ["Procedural / how-to",                        "~15%", "Both"],
            ["Numeric / specification value",              "~10%", "BM25"],
        ],
        col_widths=[Inches(2.5), Inches(1.8), Inches(2.3)])
    _note(doc, "[Observed] Query type proportions estimated from manual review of the 46-question test set in load_test.py. "
          "Not a formal annotated evaluation — these proportions are approximate.")
    _body(doc,
        "Since approximately 55% of queries benefit more from semantic retrieval, a slight "
        "semantic emphasis (w=0.6) is appropriate. BM25 weight of 0.4 ensures exact-term "
        "queries remain well-served. Equal weights (0.5/0.5) were not preferred because "
        "the query distribution is not equal. A formal weight optimisation against a "
        "labelled evaluation set would be more rigorous and is listed as a recommended "
        "improvement."
    )
    doc.add_paragraph()

    _heading(doc, "Reciprocal Rank Fusion (RRF)", 2)
    doc.add_paragraph()
    _body(doc,
        "RRF is the merging algorithm used by EnsembleRetriever. It scores each document "
        "by summing 1/(k + rank_i) across the two ranked lists, where k=60 by default. "
        "This means a document ranked 1st in both lists scores higher than a document "
        "ranked 1st in only one list. RRF is rank-position-based — it does not require "
        "score normalisation between the two arms, which is a practical advantage because "
        "BM25 and cosine scores are on different scales."
    )
    _note(doc, "[Paper] Cormack et al. (2009) 'Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank "
          "Learning Methods' — ACM SIGIR 2009. k=60 default is from this paper as the constant that minimises "
          "sensitivity to the specific value chosen.")
    doc.add_paragraph()

    _heading(doc, "Query enrichment", 2)
    doc.add_paragraph()
    _note(doc, "[Code] elastic/retriever.py — query_enrichment(), lines 142–188")
    _body(doc,
        "Before executing the search, the query is rewritten by the fast LLM. The rewrite "
        "fixes spelling, expands acronyms, adds synonyms, and incorporates prior chat context "
        "when available. Unicode NFC normalisation is applied before and after rewriting to "
        "handle composed vs decomposed Indian script characters. Both the original and the "
        "rewritten queries are used in the BM25 should-clauses — enrichment adds signal "
        "without discarding original terms."
    )
    doc.add_paragraph()

    _heading(doc, "Full table chunk recovery", 2)
    doc.add_paragraph()
    _note(doc, "[Code] elastic/retriever.py — get_full_table_chunks(), lines 49–82")
    _body(doc,
        "If the top-k results contain any chunk with content_type='table', all chunks "
        "for that table_id are fetched (size=200) and merged into the context. This "
        "prevents the known failure mode where a partial table row is returned without "
        "column headers, making the LLM unable to interpret the data correctly."
    )
    doc.add_paragraph()

    _heading(doc, "Adaptive (creative) retrieval", 2)
    doc.add_paragraph()
    _note(doc, "[Code] app/services/result_evaluation_service.py")
    _body(doc,
        "For complex queries, a single retrieval pass may not return sufficient context. "
        "The ResultEvaluationService sends the query and top-3 result summaries to the "
        "fast LLM and asks it to rate sufficiency (0.0–1.0 confidence score). The "
        "threshold starts at 0.7 and decreases by 0.1 per iteration (floor 0.5) to "
        "avoid infinite loops on ambiguous queries. If results are insufficient, the LLM "
        "generates 2–3 focused sub-queries targeting identified gaps, and a new hybrid "
        "search runs for each. Maximum 3 iterations; maximum wall time 120 seconds."
    )
    doc.add_paragraph()
    _add_figure(doc, adapt_flow,
        "Adaptive retrieval loop — derived from elastic/retriever.py and result_evaluation_service.py",
        width=Inches(6.2))

    _heading(doc, "Conclusion", 2)
    doc.add_paragraph()
    _body(doc,
        "The hybrid retrieval design is justified by published literature on lexical vs "
        "semantic retrieval complementarity. The weight setting (0.4/0.6) is a reasoned "
        "choice based on observed query distribution, not arbitrary. Query enrichment, "
        "full-table recovery, and adaptive search address specific, concrete failure modes "
        "of naive RAG retrieval. All mechanisms are traceable to code."
    )
    doc.add_page_break()

    # ═══════════════════════════════════════════════════════════════════════════
    # §4 PERFORMANCE OBSERVATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    _heading(doc, "Performance Observations", 1)
    doc.add_paragraph()
    _note(doc, "[Observed] Based on load_test.py concurrent user tests. "
          "No formal SLA benchmark was conducted against a labelled Q&A set.")
    doc.add_paragraph()
    _table(doc,
        ["Observation", "Evidence"],
        [
            ["Latency is dominated by LLM generation, not retrieval",
             "TTFB (time to first byte) is low relative to total response time, "
             "meaning the retrieval pipeline completes quickly and the GPU server "
             "generation is the bottleneck."],
            ["Retrieval quality does not degrade under concurrent load",
             "Answer character length remained stable across 10 concurrent users, "
             "indicating no retriever contention or degraded context assembly."],
            ["10 concurrent users handled without connection errors",
             "All requests succeeded (100% success rate) at 10 concurrent users "
             "with the async FastAPI + Uvicorn configuration."],
            ["P90 latency within acceptable range",
             "P90 total response time stayed within the 10-second single-query "
             "informal target under 10 concurrent users."],
        ],
        col_widths=[Inches(2.4), Inches(4.2)])
    doc.add_paragraph()
    doc.add_page_break()

    # ═══════════════════════════════════════════════════════════════════════════
    # §5 IMPROVEMENTS AND FURTHER STEPS
    # ═══════════════════════════════════════════════════════════════════════════
    _heading(doc, "Identified Gaps and Recommended Improvements", 1)
    doc.add_paragraph()
    _body(doc,
        "The following gaps exist in the current evaluation and in the pipeline itself. "
        "They do not invalidate the conclusions above, but should be addressed before "
        "any significant configuration change (LLM upgrade, embedding model swap, "
        "chunk size change)."
    )
    doc.add_paragraph()

    _heading(doc, "No formal retrieval evaluation set", 2)
    doc.add_paragraph()
    _body(doc,
        "The current evaluation relies on load testing and qualitative observation. "
        "There is no ground-truth Q&A set with labelled relevant chunks against which "
        "to measure Precision@k, Recall@k, or nDCG@10 on the actual Sachet document corpus."
    )
    _body(doc,
        "Recommended action: build a test set of 100–200 question / answer / source-chunk "
        "triples from the target documents and run RAGAS evaluation "
        "(Es et al. 2023, arXiv:2309.15217) to get objective Faithfulness, Answer Relevancy, "
        "Context Precision, and Context Recall scores. This set should be re-run before "
        "and after any LLM upgrade or pipeline change."
    )
    doc.add_paragraph()

    _heading(doc, "Hybrid weights not formally optimised", 2)
    doc.add_paragraph()
    _body(doc,
        "The w_BM25=0.4 / w_vector=0.6 split is based on qualitative query type analysis, "
        "not a grid search against labelled data. Once a RAGAS evaluation set exists, "
        "a weight sweep over [0.1, 0.2, ..., 0.9] would identify the empirically "
        "optimal split for the specific Sachet document corpus."
    )
    doc.add_paragraph()

    _heading(doc, "Chunk size not empirically tuned", 2)
    doc.add_paragraph()
    _body(doc,
        "chunk_size=2000 and overlap=400 are set based on the embedding model's context "
        "window and standard practice, not from an ablation study on this corpus. "
        "Different document types (dense policy text vs structured tables) may benefit "
        "from different chunk sizes. Recommended: evaluate Context Precision and Recall "
        "(via RAGAS) at chunk sizes of 1000, 1500, and 2000 to confirm the current "
        "setting is optimal for this corpus."
    )
    doc.add_paragraph()

    _heading(doc, "No cross-encoder reranking", 2)
    doc.add_paragraph()
    _body(doc,
        "RRF merging is rank-position-based. It does not re-score each candidate chunk "
        "against the specific query. A cross-encoder reranker (e.g. BAAI/bge-reranker-v2-m3, "
        "which is the reranking companion to bge-m3) applied to the top-15 RRF results "
        "would improve Precision@5 by re-scoring query-chunk relevance directly. "
        "Trade-off: adds ~200–500ms on CPU or ~50ms on GPU per query."
    )
    doc.add_paragraph()

    _heading(doc, "Translation quality not evaluated", 2)
    doc.add_paragraph()
    _body(doc,
        "IndicTrans2 is used to translate English answers to 22 Indian languages, but no "
        "quality evaluation has been conducted. Recommended: collect 20–30 reference "
        "translations per major language from a native speaker and compute chrF++ scores "
        "(Popovic 2017, arXiv:1701.04288) after each IndicTrans2 model update. chrF++ "
        "measures character n-gram overlap between system and reference translations, "
        "which is more appropriate than BLEU for morphologically rich Indian languages."
    )
    doc.add_paragraph()

    _heading(doc, "Summary table", 2)
    doc.add_paragraph()
    _table(doc,
        ["Gap", "Impact if unaddressed", "Recommended action"],
        [
            ["No formal evaluation set",
             "Cannot quantify improvement or regression from any change",
             "Build RAGAS Q&A test set (100–200 items)"],
            ["Hybrid weights not optimised",
             "May not be the best split for this specific corpus",
             "Grid search after RAGAS set exists"],
            ["Chunk size not ablated",
             "2000-char default may not be optimal for all document types",
             "RAGAS evaluation at 1000/1500/2000"],
            ["No cross-encoder reranking",
             "Precision@5 lower than achievable with the same retrieval budget",
             "Add bge-reranker-v2-m3 as optional post-retrieval step"],
            ["Translation not evaluated",
             "Indian language output quality unknown for domain-specific vocabulary",
             "chrF++ evaluation per major language"],
        ],
        col_widths=[Inches(1.6), Inches(2.4), Inches(2.6)])

    doc.add_paragraph()
    doc.add_page_break()

    # ═══════════════════════════════════════════════════════════════════════════
    # REFERENCES
    # ═══════════════════════════════════════════════════════════════════════════
    _heading(doc, "References", 1)
    doc.add_paragraph()
    _body(doc,
        "All links below are to the original paper or official model card. "
        "arXiv links resolve to the abstract page where the full PDF is freely available."
    )
    doc.add_paragraph()

    _ref_line(doc,
        "[1] Chen et al. (2024) — BGE M3-Embedding: Multi-Lingual, Multi-Functionality, "
        "Multi-Granularity Text Embeddings Through Self-Knowledge Distillation  "
        "(bge-m3 model paper — Table 3 cited for MIRACL dense retrieval score)",
        "https://arxiv.org/abs/2309.07597")

    _ref_line(doc,
        "[2] BAAI/bge-m3 model card on HuggingFace  "
        "(context window, language list, dimension specification)",
        "https://huggingface.co/BAAI/bge-m3")

    _ref_line(doc,
        "[3] Zhang et al. (2023) — MIRACL: A Multilingual Retrieval Dataset Covering "
        "18 Diverse Languages  "
        "(definition of MIRACL benchmark and nDCG@10 metric)",
        "https://arxiv.org/abs/2210.09984")

    _ref_line(doc,
        "[4] intfloat/multilingual-e5-large model card on HuggingFace  "
        "(context window, language support, MIRACL score cited from this card)",
        "https://huggingface.co/intfloat/multilingual-e5-large")

    _ref_line(doc,
        "[5] sentence-transformers/all-MiniLM-L6-v2 model card on HuggingFace  "
        "(English-only limitation, 256-token context, 384 dimensions)",
        "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2")

    _ref_line(doc,
        "[6] OpenAI — Embeddings guide (platform documentation)  "
        "(text-embedding-3-small model specifications and multilingual capabilities)",
        "https://platform.openai.com/docs/guides/embeddings")

    _ref_line(doc,
        "[7] Cormack, Clarke & Buettcher (2009) — Reciprocal Rank Fusion Outperforms "
        "Condorcet and Individual Rank Learning Methods  — ACM SIGIR 2009  "
        "(RRF algorithm and k=60 constant cited from this paper — direct PDF from University of Waterloo)",
        "https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf")

    _ref_line(doc,
        "[8] Luan et al. (2021) — Sparse, Dense, and Attentional Representations for "
        "Text Retrieval  — Transactions of the ACL  "
        "(hybrid retrieval outperforming single-arm retrieval on open-domain QA cited from this paper)",
        "https://arxiv.org/abs/2005.00181")

    _ref_line(doc,
        "[9] Es et al. (2023) — RAGAS: Automated Evaluation of Retrieval Augmented Generation  "
        "(Faithfulness, Answer Relevancy, Context Precision, Context Recall metrics)",
        "https://arxiv.org/abs/2309.15217")

    _ref_line(doc,
        "[10] Popovic (2017) — chrF++: words helping character n-grams  — WMT 2017  "
        "(chrF++ metric for translation evaluation cited for IndicTrans2 quality assessment)",
        "https://aclanthology.org/W17-4770")

    _ref_line(doc,
        "[11] LangChain documentation — RecursiveCharacterTextSplitter  "
        "(chunking overlap guidance and separator hierarchy referenced)",
        "https://python.langchain.com/docs/how_to/recursive_text_splitter/")

    doc.add_paragraph()
    _body(doc, "[ END OF DOCUMENT ]")

    doc.save(OUT_DOCX)
    print(f"Saved → {OUT_DOCX}")


if __name__ == "__main__":
    build_document()
