"""Turn a Kiwix page or PDF into plain text, keeping headings, lists, numbered steps and table rows.

Adapted from Survival LLM's library/build_library.py (MIT License, Copyright (c) 2026 Ronny Fernandez; see
LICENSE.survival-llm). Changes: pages with no main content fall back to their whole body instead of trafilatura;
control characters are removed before parsing, since lxml refuses them; and a dropped section's subsections are
not dropped twice.
"""
import os
import re
import subprocess
import tempfile

import lxml.html

MIN_CHARS = 300  # shorter pages are navigation, stubs or errors
CONTROL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # lxml won't set text containing these

HEADINGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "#### ", "h6": "#### "}
BLOCKS = {"p", "div", "section", "article", "ul", "ol", "dl", "dt", "dd", "table", "pre", "blockquote",
          "figure", "figcaption", "details", "summary", "main", "center", "hr", "caption"}
DROP_XPATH = (".//script|.//style|.//noscript|.//template|.//svg|.//button|.//form|.//nav|.//footer|.//header"
              "|.//aside|.//sup[contains(@class,'reference')]")
DROP_CLASS = re.compile(
    r"\b(mw-editsection|references|mw-references-wrap|reflist|navbox|vertical-navbox|sidebar|metadata|ambox"
    r"|noprint|catlinks|zim-footer|mw-empty-elt|printfooter|mw-jump-link|toc|mw-cite-backlink|comments"
    r"|js-post-comments-component|credit-author-team-container)\b")
DROP_SECTIONS = {"references", "external links", "see also", "further reading", "notes", "sources",
                 "bibliography", "citations", "footnotes", "notes and references", "references and notes"}
TITLE_SUFFIX = re.compile(
    r"\s*[|:\-–—]\s*(NHS|Ready\.gov|FEMA|CDC|Travelers' Health|MedlinePlus[^|]*|iFixit[^|]*|Appropedia[^|]*"
    r"|Wikipedia|WikEM)\s*$", re.I)

# PDFs inside books that are only named by file: their real titles.
MILMED = "irp.fas.org/doddir/milmed/"
USDA = "files/GUIDE0{}_HomeCan_rev0715.pdf"
PDF_TITLES = {
    MILMED + "corpsman-pt1.pdf": "Hospital Corpsman (NAVEDTRA 14295), part 1",
    MILMED + "corpsman-pt2.pdf": "Hospital Corpsman (NAVEDTRA 14295), part 2",
    MILMED + "corpsman-pt3.pdf": "Hospital Corpsman (NAVEDTRA 14295), part 3",
    MILMED + "dosimetry.pdf": "Personnel Dosimetry Guidance (DA Pam 40-18)",
    MILMED + "duequip.pdf": "Handling Equipment Contaminated with Depleted Uranium (DA Pam 700-48)",
    MILMED + "first.pdf": "First Aid (FM 4-25.11)",
    MILMED + "malaria.pdf": "Navy Pocket Guide to Malaria Prevention and Control",
    MILMED + "milderm.pdf": "Military Dermatology (Textbook of Military Medicine)",
    MILMED + "preventive.pdf": "Preventive Medicine (DA Pam 40-11)",
    MILMED + "prevserv.pdf": "Preventive Medicine Services (FM 4-02.17)",
    MILMED + "rhpm.pdf": "Radiation Health Protection Manual (NAVMED P-5055)",
    MILMED + "sanitation.pdf": "Unit Field Sanitation Team (FM 4-25.12)",
    MILMED + "ships.pdf": "The Ship's Medicine Chest and Medical Aid at Sea",
    MILMED + "soldiers.pdf": "First Aid for Soldiers (FM 21-11, 1988)",
    MILMED + "sterile.pdf": "Sterilizing Medical, Surgical and Dental Equipment (Army technical bulletin)",
    MILMED + "surghand.pdf": "Division and Brigade Surgeons' Handbook (FM 4-02.21)",
    MILMED + "warpsychiatry.pdf": "War Psychiatry (Textbook of Military Medicine)",
    "files/INTRO_HomeCanrev0715.pdf": "USDA Complete Guide to Home Canning: Introduction",
    USDA.format(1): "USDA Home Canning Guide 1: Principles of Home Canning",
    USDA.format(2): "USDA Home Canning Guide 2: Selecting, Preparing, and Canning Fruit and Fruit Products",
    USDA.format(3): "USDA Home Canning Guide 3: Selecting, Preparing, and Canning Tomatoes and Tomato Products",
    USDA.format(4): "USDA Home Canning Guide 4: Selecting, Preparing, and Canning Vegetables and Vegetable Products",
    USDA.format(5): "USDA Home Canning Guide 5: Preparing and Canning Poultry, Red Meats, and Seafoods",
    USDA.format(6): "USDA Home Canning Guide 6: Preparing and Canning Fermented Foods and Pickled Vegetables",
    USDA.format(7): "USDA Home Canning Guide 7: Preparing and Canning Jams and Jellies",
}


def _heading_level(el):
    return int(el.tag[1]) if isinstance(el.tag, str) and el.tag in HEADINGS else None


def _drop_sections(node):
    """Remove References / External links / See also sections, whatever the markup style."""
    for h in node.xpath(".//h2|.//h3|.//h4"):
        if not any(ancestor is node for ancestor in h.iterancestors()):
            continue  # inside a section dropped already, such as Footnotes under References
        if " ".join(h.text_content().split()).lower() not in DROP_SECTIONS:
            continue
        anchor = h
        parent = h.getparent()
        if parent.tag == "div" and "mw-heading" in (parent.get("class") or ""):
            anchor = parent  # MediaWiki 1.43+ wraps headings in <div class="mw-heading">
        wrapper = anchor.getparent()
        if wrapper is not None and wrapper.tag in ("section", "details") and len(wrapper) and wrapper[0] is anchor:
            wrapper.drop_tree()
            continue
        if wrapper is not None and wrapper.tag == "summary":
            wrapper.getparent().drop_tree()
            continue
        level = int(h.tag[1])
        sib = anchor.getnext()
        anchor.drop_tree()
        while sib is not None:
            inner = sib if _heading_level(sib) else (sib[0] if len(sib) and _heading_level(sib[0]) else None)
            if inner is not None and _heading_level(inner) <= level:
                break
            nxt = sib.getnext()
            sib.drop_tree()
            sib = nxt


def node_text(node):
    """Element tree to plain text, keeping headings, numbered steps, bullets and table rows."""
    for bad in node.xpath(DROP_XPATH):
        bad.drop_tree()
    for el in node.xpath(".//*[@class]"):
        if DROP_CLASS.search(el.get("class")):
            el.drop_tree()
    for ol in node.iter("ol"):
        for n, li in enumerate((c for c in ol if c.tag == "li"), 1):
            li.set("data-n", str(n))
    for el in node.iter():
        if not isinstance(el.tag, str):
            continue
        t = el.tag
        if t in HEADINGS:
            el.text = "\n\n" + HEADINGS[t] + (el.text or "")
            el.tail = "\n\n" + (el.tail or "")
        elif t == "li":
            el.text = (f"\n{el.get('data-n')}. " if el.get("data-n") else "\n- ") + (el.text or "")
        elif t == "tr":
            el.text = "\n" + (el.text or "")
        elif t in ("td", "th"):
            el.tail = " | " + (el.tail or "")
        elif t == "br":
            el.tail = "\n" + (el.tail or "")
        elif t in BLOCKS:
            el.text = "\n\n" + (el.text or "")
            el.tail = "\n\n" + (el.tail or "")
    lines = []
    for line in node.text_content().split("\n"):
        line = re.sub(r"[ \t ​]+", " ", line).strip()
        line = re.sub(r"(\s*\|)+\s*$", "", line)
        if line in ("-", "#", "##", "###", "####") or re.fullmatch(r"\d+\.", line):
            line = ""
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def clean_title(title):
    return TITLE_SUFFIX.sub("", " ".join(title.split())).strip()


def _se_author(post, question=False):
    """ ' by <name>' for a Stack Exchange post (its license asks for the author's name), or ''."""
    sigs = post.xpath(".//div[contains(@class,'post-signature')]")
    if question:
        sigs = [s for s in sigs if "owner" in (s.get("class") or "")] or sigs
    name = sigs[-1].xpath(".//*[contains(@class,'s-user-card--link')]") if sigs else []
    name = " ".join(name[0].text_content().split()) if name else ""
    return f" by {name}" if name else ""


def _stack_exchange(doc):
    """A question with its best answers (accepted first, then by score); None when nobody answered."""
    q = doc.xpath("//div[@id='question']")
    if not q:
        return None
    body = q[0].xpath(".//div[contains(@class,'js-post-body')]")
    answers = []
    for a in doc.xpath("//div[contains(concat(' ', @class, ' '), ' answer ')][@data-score]"):
        a_body = a.xpath(".//div[contains(@class,'js-post-body')]")
        if a_body:
            answers.append((int(a.get("data-score") or 0), "accepted-answer" in (a.get("class") or ""), a, a_body[0]))
    if not body or not answers:
        return None
    answers.sort(key=lambda x: (not x[1], -x[0]))
    parts = [f"Question{_se_author(q[0], question=True)} (score {q[0].get('data-score', '0')}):\n\n"
             + node_text(body[0])]
    for score, accepted, post, a_body in answers[:5]:
        if score >= 0:
            parts.append(f"## Answer{_se_author(post)} (score {score}{', accepted' if accepted else ''})\n\n"
                         + node_text(a_body))
    return "\n\n".join(parts)


def html_to_text(html, kind):
    doc = lxml.html.fromstring(CONTROL.sub(b"", html))
    if kind == "se":
        return _stack_exchange(doc)
    if kind == "wiki":
        found = doc.xpath("//*[@id='mw-content-text']") or doc.xpath("//*[contains(@class,'mw-parser-output')]")
        if found:  # otherwise (a scraped wiki) read it like any other page
            _drop_sections(found[0])
            return node_text(found[0])
    author = doc.xpath("//div[contains(@class,'guide-author')]")  # iFixit: "Written By: <name>"
    author = " ".join(author[0].text_content().split()) if author else ""
    found = doc.xpath("//main") or doc.xpath("//article") or doc.xpath("//*[@id='content']")
    text = node_text(found[0]) if found else ""
    if len(text) < MIN_CHARS:
        body = doc.xpath("//body")
        text = node_text(body[0]) if body else ""
    return f"{author}\n\n{text}" if author and text else text


def pdf_to_text(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        result = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", f.name, "-"], capture_output=True, timeout=600)
    text = result.stdout.decode("utf-8", "replace").replace("\f", "\n\n")
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paras if p)


def pdf_title(path, title, text):
    """A PDF's title: a known one, else its file name, led by its first line when zimgit only numbered it."""
    title = title if title and title != path else os.path.basename(path)
    title = PDF_TITLES.get(path, re.sub(r"\.pdf$", "", title.replace("_", " "), flags=re.I))
    if re.search(r"\(\d+\)$", title):  # zimgit names files "Water (7)"
        first = next((p for p in text.split("\n\n") if len(p) >= 12), "")
        if first:
            title = (first[:80].rsplit(" ", 1)[0] if len(first) > 80 else first) + f" [{title}]"
    return title
