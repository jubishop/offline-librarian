"""Cut an article into the passages the library searches.

Adapted from Survival LLM's library/passages.py (MIT License, Copyright (c) 2026 Ronny Fernandez; see
LICENSE.survival-llm). Changes: passages are returned as offsets into the article's text, so they can be read
back out of the stored article instead of being stored twice.
"""
import re


def _pieces(paras, target, hard):
    """(start, end, heading or None) for each paragraph of "\n\n".join(paras), long paragraphs cut at sentences."""
    pos = 0
    for para in paras:
        if para.startswith("#"):
            yield pos, pos + len(para), para.lstrip("#").strip()
        else:
            start, rest = pos, para
            while len(rest) > hard:
                cut = rest.rfind(". ", target // 2, hard)
                cut = cut + 1 if cut > 0 else hard
                yield start, start + cut, None
                skip = len(rest[cut:]) - len(rest[cut:].lstrip())
                start, rest = start + cut + skip, rest[cut + skip:]
            if rest:
                yield start, start + len(rest), None
        pos += len(para) + 2


def split_passages(text, target=1500, hard=3000):
    """(text, passages): the text with paragraphs separated by one blank line, and its passages as
    (start, end, heading) on paragraph boundaries, about target characters each."""
    paras = [p.strip() for p in re.split(r"\n{2,}", text)]
    paras = [p for p in paras if p]
    out, start, end, size, heading, passage_heading = [], None, None, 0, "", ""
    for piece_start, piece_end, piece_heading in _pieces(paras, target, hard):
        length = piece_end - piece_start
        if piece_heading is not None:
            if start is not None and size > 200:
                out.append((start, end, passage_heading))
                start, size = None, 0
            heading = piece_heading
        elif start is not None and size + length > target:
            out.append((start, end, passage_heading))
            start, size = None, 0
        if start is None:
            start, passage_heading = piece_start, heading
        end, size = piece_end, size + length + 2
    if start is not None:
        out.append((start, end, passage_heading))
    return "\n\n".join(paras), out
