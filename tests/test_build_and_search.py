"""Building the library from Kiwix books, then searching and reading it."""
import os
import tempfile
import unittest

from books import Page, pdf, wiki_page, write_book
from librarian import build
from librarian.library import Library

SHIVERING = ("Hypothermia is a body temperature below 35 degrees. Shivering stops as it gets worse, and the person "
             "becomes confused and sleepy. Move them somewhere warm, remove wet clothing and wrap them in blankets. "
             "Call emergency services, keep them lying flat, and cover the head and neck as well as the body.")
REWARMING = ("Rewarm the core first. Warm sweet drinks help only if the person is awake and can swallow. Do not rub "
             "the arms and legs, and handle the person gently because the cold heart is prone to arrhythmia.")
STARTER = ("A sourdough starter is flour and water fermented by wild yeast and lactic acid bacteria. Feed it equal "
           "weights of flour and water every day, and keep it somewhere warm until it doubles after feeding. A healthy "
           "starter smells pleasantly sour, rises within hours of a feed, and is ready to bake with at its peak.")
QUESTION = """<html><body><div id="question" data-score="7"><div class="js-post-body"><p>My sourdough starter
smells like nail polish remover after a week. Is it ruined, or can I save it? I feed it once a day.</p></div>
<div class="post-signature owner"><a class="s-user-card--link">Rosa</a></div></div>
<div class="answer" data-score="3"><div class="js-post-body"><p>Throw it out and buy commercial yeast instead,
because the smell means it has spoiled beyond saving and will never rise properly again.</p></div>
<div class="post-signature"><a class="s-user-card--link">Bram</a></div></div>
<div class="answer accepted-answer" data-score="12"><div class="js-post-body"><p>The acetone smell means the
starter is hungry. Feed it twice a day with equal weights of flour and water, and it recovers in a few days.</p>
</div><div class="post-signature"><a class="s-user-card--link">Alice</a></div></div></body></html>"""


def build_quietly(home):
    lines = []
    build.build(home, workers=2, log=lines.append)
    return lines


class BuildTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name

    def library(self):
        library = Library(os.path.join(self.home, "library.sqlite"))
        self.addCleanup(library.close)
        return library

    def test_finds_a_wiki_article_without_its_references(self):
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim", [
            Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING],
                                                         ["Smith J. Cold injury. Wilderness Journal 2020."])),
            Page("Sourdough", "Sourdough", wiki_page("Sourdough", [STARTER])),
            Page("Stub", "Stub", wiki_page("Stub", ["Too short to keep."])),
        ], redirects=[("Cold_injury", "Cold injury", "Hypothermia")])
        build_quietly(self.home)
        hits = self.library().search("someone is shivering and confused after the cold")
        self.assertEqual(hits[0].title, "Hypothermia")
        self.assertEqual(hits[0].source, "WikEM emergency medicine")
        self.assertEqual(hits[0].url, "https://wikem.org/wiki/Hypothermia")
        article = self.library().article(hits[0].id)
        self.assertIn("Do not rub the arms and legs", article.text)
        self.assertNotIn("Wilderness Journal", article.text)
        self.assertIn("CC BY-SA 4.0", article.license)
        self.assertEqual(self.library().stats()[0], 2)  # the redirect and the stub add no articles

    def test_long_articles_become_several_passages_covering_the_text(self):
        paragraphs = [f"Paragraph {n} about water storage, rotation and containers. " * 8 for n in range(12)]
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim",
                   [Page("Water", "Water", wiki_page("Water", paragraphs))])
        build_quietly(self.home)
        hits = self.library().search("water storage containers")
        self.assertEqual(len(hits), 1)  # one passage per article
        article = self.library().article(hits[0].id)
        self.assertGreater(len(article.passages), 3)
        self.assertTrue(all(end - start <= 3000 for _, start, end in article.passages))
        self.assertIn("Paragraph 11", article.text[article.passages[-1][1]:article.passages[-1][2]])

    def test_stack_exchange_keeps_answered_questions_with_their_authors(self):
        write_book(self.home, "cooking.stackexchange.com_en_all", "cooking.stackexchange.com_en_all_2026-10.zim", [
            Page("questions/1/starter-smells-like-acetone", "Starter smells like acetone", QUESTION),
            Page("users/2/rosa", "Rosa", wiki_page("Rosa", [STARTER])),
        ])
        build_quietly(self.home)
        hits = self.library().search("sourdough starter smells like nail polish")
        self.assertEqual([hit.title for hit in hits], ["Starter smells like acetone"])
        text = self.library().article(hits[0].id).text
        self.assertIn("Question by Rosa (score 7)", text)
        self.assertLess(text.index("Answer by Alice (score 12, accepted)"), text.index("Answer by Bram (score 3)"))

    def test_reads_the_text_of_pdfs(self):
        lines = ["Emergency Disinfection of Drinking Water",
                 "Add 8 drops of unscented household chlorine bleach to each gallon of clear water.",
                 "Stir the mixture well and let it stand for 30 minutes before drinking it.",
                 "If the water does not have a slight chlorine odor, repeat the dose and wait 15 more minutes.",
                 "Store the disinfected water in clean, covered containers away from sunlight."]
        write_book(self.home, "zimgit-water_en", "zimgit-water_en_2024-08.zim", [
            Page("home", "home", "<html><body>Library</body></html>"),
            Page("files/Water (1).pdf", "files/Water (1).pdf", pdf(lines), mimetype="application/pdf"),
        ])
        build_quietly(self.home)
        hits = self.library().search("how many drops of bleach per gallon")
        # zimgit only numbers its PDFs, so the title leads with their text, as Survival LLM's did.
        self.assertTrue(hits[0].title.startswith("Emergency Disinfection of Drinking Water"), hits[0].title)
        self.assertTrue(hits[0].title.endswith(" [Water (1)]"), hits[0].title)
        self.assertIn("8 drops", hits[0].text)
        self.assertEqual(hits[0].url, "")  # zimgit's PDFs have no web address

    def test_wikipedia_skips_articles_wikimed_already_has(self):
        write_book(self.home, "wikipedia_en_medicine nopic", "wikipedia_en_medicine_nopic_2026-10.zim",
                   [Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING]))])
        write_book(self.home, "wikipedia_en_top1m nopic", "wikipedia_en_top1m_nopic_2026-04.zim", [
            Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING])),
            Page("Sourdough", "Sourdough", wiki_page("Sourdough", [STARTER])),
        ])
        build_quietly(self.home)
        hits = self.library().search("hypothermia shivering confused")
        self.assertEqual([(hit.title, hit.source) for hit in hits], [("Hypothermia", "WikiMed (Wikipedia medicine)")])
        self.assertEqual(self.library().search("sourdough starter")[0].source, "Wikipedia")

    def test_building_again_adds_new_books_and_redoes_replaced_ones(self):
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-09.zim",
                   [Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING]))])
        build_quietly(self.home)
        self.assertIn("wikem: already built", build_quietly(self.home))
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim",
                   [Page("Sourdough", "Sourdough", wiki_page("Sourdough", [STARTER]))])
        write_book(self.home, "cooking.stackexchange.com_en_all", "cooking.stackexchange.com_en_all_2026-10.zim",
                   [Page("questions/1/starter-smells-like-acetone", "Starter smells like acetone", QUESTION)])
        build_quietly(self.home)
        library = self.library()
        self.assertEqual(library.search("hypothermia shivering"), [])
        self.assertEqual(library.search("sourdough starter flour")[0].title, "Sourdough")
        self.assertEqual(library.stats()[0], 2)

    def test_returns_text_that_two_books_share_only_once(self):
        # zimgit's Water and Post Disaster collections bundle many of the same PDFs.
        for label, filename in (("zimgit-water_en", "zimgit-water_en_2024-08.zim"),
                                ("zimgit-post-disaster_en", "zimgit-post-disaster_en_2024-05.zim")):
            write_book(self.home, label, filename,
                       [Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING, REWARMING]))])
        build_quietly(self.home)
        self.assertEqual(len(self.library().search("hypothermia shivering")), 1)

    def test_keeps_articles_whose_dropped_sections_hold_other_dropped_sections(self):
        # Wikipedia's flat layout: Footnotes and Bibliography sit under References, which is dropped first.
        tail = "".join(f'<div class="mw-heading mw-heading{level}"><h{level}>{name}</h{level}></div><p>{name} text</p>'
                       for level, name in [(2, "See also"), (2, "References"), (3, "Footnotes"),
                                           (3, "Bibliography"), (2, "Further reading")])
        html = f"""<html><body><div id="mw-content-text"><div class="mw-parser-output">
<p>{SHIVERING}</p><div class="mw-heading mw-heading2"><h2>Treatment</h2></div><p>{REWARMING}</p>{tail}
</div></div></body></html>"""
        write_book(self.home, "wikipedia_en_top1m nopic", "wikipedia_en_top1m_nopic_2026-04.zim",
                   [Page("Hypothermia", "Hypothermia", html)])
        lines = build_quietly(self.home)
        self.assertFalse([line for line in lines if "skipped" in line], lines)
        article = self.library().article(self.library().search("hypothermia shivering")[0].id)
        self.assertIn("## Treatment", article.text)
        self.assertIn("Do not rub the arms and legs", article.text)
        for name in ("See also", "Footnotes", "Bibliography", "Further reading"):
            self.assertNotIn(name, article.text)

    def test_keeps_pages_with_control_characters(self):
        html = f"<html><body><main><p>{SHIVERING}\x0b</p><p>{REWARMING}\x1f</p></main></body></html>"
        write_book(self.home, "ifixit_en_all", "ifixit_en_all_2025-12.zim", [Page("Guide/1", "Rewarming", html)])
        lines = build_quietly(self.home)
        self.assertFalse([line for line in lines if "skipped" in line], lines)
        self.assertEqual(self.library().search("hypothermia shivering")[0].title, "Rewarming")

    def test_rebuilds_the_books_it_is_asked_to(self):
        write_book(self.home, "wikem_en_all nopic", "wikem_en_all_nopic_2026-10.zim",
                   [Page("Hypothermia", "Hypothermia", wiki_page("Hypothermia", [SHIVERING]))])
        build_quietly(self.home)
        lines = []
        build.build(self.home, workers=1, rebuild=["wikem"], log=lines.append)
        self.assertIn("wikem: building from wikem_en_all_nopic_2026-10.zim", lines)
        self.assertEqual(self.library().search("hypothermia")[0].title, "Hypothermia")
        with self.assertRaises(ValueError):
            build.build(self.home, workers=1, rebuild=["not-a-source"], log=lines.append)


if __name__ == "__main__":
    unittest.main()
