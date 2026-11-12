"""Small helpers on top of python-docx for a journal-style manuscript:
numbered headings, Word-native equations (LaTeX -> MathML -> OMML), figures, tables
and numbered citations."""
from __future__ import annotations

import re
from copy import deepcopy

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import parse_xml
from docx.oxml.ns import qn, nsdecls
from docx.shared import Pt, Cm, RGBColor, Inches
from lxml import etree
import latex2mathml.converter

XSL = r"C:/Program Files/Microsoft Office/root/Office16/MML2OMML.XSL"
_xslt = None


def _omml(latex: str):
    global _xslt
    if _xslt is None:
        _xslt = etree.XSLT(etree.parse(XSL))
    mml = latex2mathml.converter.convert(latex)
    return _xslt(etree.fromstring(mml.encode()))


class Manuscript:
    FONT = "Times New Roman"

    def __init__(self, labels=None):
        """labels: label -> number from a first build pass, so that text can refer forward (@fig:x, @tab:x, @sec:x, @eq:x)."""
        self.known = dict(labels or {})
        self.labels = {}
        self.unresolved = set()
        self.doc = Document()
        sec = self.doc.sections[0]
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        for m in ("left_margin", "right_margin"):
            setattr(sec, m, Cm(2.5))
        sec.top_margin = sec.bottom_margin = Cm(2.5)
        st = self.doc.styles
        normal = st["Normal"]
        normal.font.name = self.FONT
        normal.font.size = Pt(11)
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), self.FONT)
        pf = normal.paragraph_format
        pf.space_after = Pt(6)
        pf.line_spacing = 1.5
        for lvl, size in ((1, 13), (2, 12), (3, 11)):
            h = st[f"Heading {lvl}"]
            h.font.name = self.FONT
            h.element.rPr.rFonts.set(qn("w:eastAsia"), self.FONT)
            h.font.size = Pt(size)
            h.font.bold = True
            h.font.italic = lvl == 3
            h.font.color.rgb = RGBColor(0, 0, 0)
            h.paragraph_format.space_before = Pt(12 if lvl == 1 else 9)
            h.paragraph_format.space_after = Pt(6)
            h.paragraph_format.keep_with_next = True
            h.paragraph_format.line_spacing = 1.15
        self.counters = [0, 0, 0]
        self.eq_no = 0
        self.fig_no = 0
        self.tab_no = 0
        self.tab_prefix = ""   # e.g. "S5." in a supplement (numbering restarts per section)
        self.fig_prefix = ""
        self.refs = {}         # key -> formatted reference string
        self.cite_order = []   # keys in order of first citation
        self._add_page_numbers()

    # ---------------------------------------------------------------- basics
    def _add_page_numbers(self):
        footer = self.doc.sections[0].footer
        p = footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
            if tag:
                el = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="{tag}"/>')
            else:
                el = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve">{text}</w:instrText>')
            run._r.append(el)

    def set_references(self, refs: dict):
        self.refs = refs

    def _cite(self, keys):
        nums = []
        for k in keys:
            if k not in self.refs:
                raise KeyError(f"unknown reference {k}")
            if k not in self.cite_order:
                self.cite_order.append(k)
            nums.append(self.cite_order.index(k) + 1)
        nums = sorted(set(nums))
        # compress ranges
        out, i = [], 0
        while i < len(nums):
            j = i
            while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
                j += 1
            out.append(f"{nums[i]}–{nums[j]}" if j - i >= 2 else ", ".join(str(n) for n in nums[i:j + 1]))
            i = j + 1
        return "[" + ", ".join(out) + "]"

    def _runs(self, p, text, size=None, italic_all=False):
        """Markup: **bold**, *italic*, ^{sup}, _{sub}, [@key1;key2] citations, $latex$ inline math."""
        text = self._xref(text)
        pattern = re.compile(r"(\*\*.+?\*\*|\*.+?\*|\^\{.+?\}|_\{.+?\}|\[@.+?\]|\$.+?\$)")
        for tok in pattern.split(text):
            if not tok:
                continue
            if tok.startswith("[@"):
                r = p.add_run(self._cite([k.strip() for k in tok[2:-1].split(";")]))
            elif tok.startswith("$") and tok.endswith("$") and len(tok) > 2:
                p._p.append(deepcopy(_omml(tok[1:-1]).getroot()))
                continue
            elif tok.startswith("**"):
                r = p.add_run(tok[2:-2]); r.bold = True
            elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
                r = p.add_run(tok[1:-1]); r.italic = True
            elif tok.startswith("^{"):
                r = p.add_run(tok[2:-1]); r.font.superscript = True
            elif tok.startswith("_{"):
                r = p.add_run(tok[2:-1]); r.font.subscript = True
            else:
                r = p.add_run(tok)
            if size:
                r.font.size = Pt(size)
            if italic_all:
                r.italic = True
        return p

    # @fig:name, or @[fig:name] when a letter follows directly (e.g. "Fig. @[fig:name]a"; safe inside f-strings)
    _XREF = re.compile(r"@\[(fig|tab|sec|eq):([A-Za-z0-9_]+)\]|@(fig|tab|sec|eq):([A-Za-z0-9_]+)")

    def _xref(self, text):
        def sub(mo):
            kind, name = (mo.group(1), mo.group(2)) if mo.group(1) else (mo.group(3), mo.group(4))
            key = f"{kind}:{name}"
            if key not in self.known and key not in self.labels:
                self.unresolved.add(key)
            return str(self.known.get(key, self.labels.get(key, "??")))
        return self._XREF.sub(sub, text)

    def _label(self, kind, label, value):
        if label:
            key = f"{kind}:{label}"
            if key in self.labels:
                raise KeyError(f"duplicate label {key}")
            self.labels[key] = value

    def para(self, text, align="justify", size=None, italic=False, space_after=None, indent=True, style=None):
        p = self.doc.add_paragraph(style=style)
        p.alignment = {"justify": WD_ALIGN_PARAGRAPH.JUSTIFY, "center": WD_ALIGN_PARAGRAPH.CENTER,
                       "left": WD_ALIGN_PARAGRAPH.LEFT}[align]
        if space_after is not None:
            p.paragraph_format.space_after = Pt(space_after)
        self._runs(p, text, size, italic)
        return p

    def bullets(self, items):
        for it in items:
            p = self.doc.add_paragraph(style="List Bullet")
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(2)
            self._runs(p, it)

    def heading(self, text, level=1, numbered=True, label=None):
        if numbered:
            self.counters[level - 1] += 1
            for i in range(level, 3):
                self.counters[i] = 0
            num = ".".join(str(c) for c in self.counters[:level])
            self._label("sec", label, num)
            text = f"{num}{'.' if level == 1 else ''} {text}"
        return self.doc.add_heading(text, level=level)

    def equation(self, latex, label=None):
        self.eq_no += 1
        self._label("eq", label, self.eq_no)
        tbl = self.doc.add_table(rows=1, cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        w = (Cm(14.5), Cm(1.5))
        for i, cell in enumerate(tbl.rows[0].cells):
            cell.width = w[i]
        c0, c1 = tbl.rows[0].cells
        p0 = c0.paragraphs[0]
        p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p0.paragraph_format.space_after = Pt(0)
        omml = _omml(latex).getroot()
        para = etree.SubElement(etree.Element("dummy"), qn("m:oMathPara"))
        para.append(deepcopy(omml))
        p0._p.append(para)
        p1 = c1.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p1.add_run(f"({self.eq_no})")
        if label:
            setattr(self, f"eq_{label}", self.eq_no)
        return self.eq_no

    def figure(self, path, caption, width_cm=16.0, label=None):
        self.fig_no += 1
        self._label("fig", label, self.fig_no)
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(path), width=Cm(width_cm))
        c = self.doc.add_paragraph()
        c.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        c.paragraph_format.line_spacing = 1.15
        r = c.add_run(f"Fig. {self.fig_prefix}{self.fig_no}. ")
        r.bold = True
        r.font.size = Pt(9.5)
        self._runs(c, caption, size=9.5)
        return self.fig_no

    def table(self, header, rows, caption, col_widths_cm=None, font_size=8.5, notes=None, label=None):
        self.tab_no += 1
        self._label("tab", label, self.tab_no)
        c = self.doc.add_paragraph()
        c.paragraph_format.keep_with_next = True
        c.paragraph_format.line_spacing = 1.15
        r = c.add_run(f"Table {self.tab_prefix}{self.tab_no}. ")
        r.bold = True
        r.font.size = Pt(9.5)
        self._runs(c, caption, size=9.5)
        t = self.doc.add_table(rows=1 + len(rows), cols=len(header))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.style = self.doc.styles["Table Grid"]
        self._booktabs(t)
        for j, h in enumerate(header):
            cell = t.rows[0].cells[j]
            cell.paragraphs[0].paragraph_format.line_spacing = 1.0
            self._runs(cell.paragraphs[0], f"**{h}**" if "_{" not in h and "^{" not in h else h, size=font_size)
            for rr in cell.paragraphs[0].runs:
                rr.bold = True
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                cell = t.rows[i + 1].cells[j]
                pp = cell.paragraphs[0]
                pp.paragraph_format.line_spacing = 1.0
                pp.paragraph_format.space_after = Pt(1)
                self._runs(pp, str(v), size=font_size)
        if col_widths_cm:
            for row in t.rows:
                for j, wcm in enumerate(col_widths_cm):
                    row.cells[j].width = Cm(wcm)
        if notes:
            n = self.doc.add_paragraph()
            n.paragraph_format.line_spacing = 1.0
            self._runs(n, notes, size=8)
        else:
            self.doc.add_paragraph().paragraph_format.space_after = Pt(2)
        return self.tab_no

    def _booktabs(self, t):
        tblPr = t._tbl.tblPr
        borders = parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            '<w:top w:val="single" w:sz="8" w:color="000000"/>'
            '<w:left w:val="nil"/><w:right w:val="nil"/>'
            '<w:bottom w:val="single" w:sz="8" w:color="000000"/>'
            '<w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>')
        for el in tblPr.findall(qn("w:tblBorders")):
            tblPr.remove(el)
        tblPr.append(borders)
        # rule under header row
        for cell in t.rows[0].cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcPr.append(parse_xml(f'<w:tcBorders {nsdecls("w")}><w:bottom w:val="single" w:sz="6" '
                                  'w:color="000000"/></w:tcBorders>'))

    def page_break(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def reference_list(self):
        for i, k in enumerate(self.cite_order):
            p = self.doc.add_paragraph()
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.left_indent = Cm(0.8)
            p.paragraph_format.first_line_indent = Cm(-0.8)
            p.paragraph_format.space_after = Pt(3)
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            self._runs(p, f"[{i + 1}]\t{self.refs[k]}", size=9.5)

    def save(self, path):
        self.doc.save(str(path))


def build_two_pass(build_fn, refs):
    """Build once to collect label numbers, then again so that forward references resolve."""
    first = Manuscript()
    first.set_references(refs)
    build_fn(first)
    m = Manuscript(labels=first.labels)
    m.set_references(refs)
    build_fn(m)
    if m.unresolved:
        raise KeyError(f"unresolved cross-references: {sorted(m.unresolved)}")
    return m
