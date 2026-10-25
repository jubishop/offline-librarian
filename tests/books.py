"""Small Kiwix books for tests, written with libzim, and a minimal PDF writer."""
import json
import os

from libzim.writer import Creator, Hint, Item, StringProvider


class Page(Item):
    def __init__(self, path, title, content, mimetype="text/html"):
        super().__init__()
        self.path, self.title, self.content, self.mimetype = path, title, content, mimetype

    def get_path(self):
        return self.path

    def get_title(self):
        return self.title

    def get_mimetype(self):
        return self.mimetype

    def get_contentprovider(self):
        return StringProvider(self.content)

    def get_hints(self):
        return {Hint.FRONT_ARTICLE: self.mimetype == "text/html", Hint.COMPRESS: True}


def write_book(home, label, filename, pages, redirects=()):
    """Write pages (and (path, title, target) redirects) to home/zim/filename and list it in the manifest."""
    folder = os.path.join(home, "zim")
    os.makedirs(folder, exist_ok=True)
    with Creator(os.path.join(folder, filename)).config_indexing(False, "eng").config_verbose(False) as creator:
        creator.set_mainpath(pages[0].path)
        for page in pages:
            creator.add_item(page)
        for path, title, target in redirects:
            creator.add_redirection(path, title, target, {Hint.FRONT_ARTICLE: True})
    manifest_path = os.path.join(folder, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
    manifest[label] = {"file": filename, "updated": "2026-10-20", "sha256": "0" * 64, "bytes": 0}
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)


def wiki_page(title, paragraphs, references=()):
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    refs = "".join(f"<li>{r}</li>" for r in references)
    return f"""<html><head><title>{title}</title></head><body><div id="mw-content-text">
<div class="mw-parser-output"><h1>{title}</h1>{body}<div class="mw-heading mw-heading2"><h2>References</h2></div>
<ol>{refs}</ol></div></div></body></html>"""


def pdf(lines):
    """A one-page PDF whose text layer is lines."""
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    content = "BT /F1 11 Tf 40 760 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in escaped) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               "/Resources << /Font << /F1 5 0 R >> >> >>",
               f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out
