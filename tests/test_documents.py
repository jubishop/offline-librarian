"""Sources that aren't Kiwix books: PDF manuals, web pages and the wikiHow dump, fetched and built."""
import offline  # noqa: F401  (tests never reach the internet)
import hashlib
import os
import tempfile
import unittest

from books import pdf
from librarian import build, documents
from librarian.library import Library
from librarian.sources import Document, DocumentSource
from test_kiwix_fetch import Site

MANUAL = pdf(["FM 4-25.11 First Aid",
              "To control bleeding, apply direct pressure to the wound with a field dressing.",
              "If bleeding continues, apply a tourniquet two inches above the wound, between it and the heart.",
              "Note the time the tourniquet was applied and never loosen it once it is in place.",
              "Treat the casualty for shock: lay them down, elevate the legs and keep them warm."])
PAGE = b"""<html><body><main><h1>How dangerous is lightning?</h1><p>The odds of being struck by lightning in a
given year are about one in a million, and about one in 15,300 over an 80-year lifetime. When thunder roars, go
indoors, and stay inside until 30 minutes after the last thunder you hear. A car with a metal roof is also safe; a
tent, a picnic shelter or a tree is not.</p></main></body></html>"""
GUIDEBOOK = pdf(["Emergency Response Guidebook 2024",
                 "Identify the hazardous material from the placard number on the truck or rail car.",
                 "Stay upwind, uphill and upstream, and keep people away from the spill.",
                 "Use the orange pages to find the initial isolation distance for the material.",
                 "Do not walk into or touch spilled material, and avoid inhaling fumes or smoke."])
WIKIHOW = ('headline,title,text\n'
           '"\nFill a pot with water.,\nBring it to a rolling boil.,\nKeep it boiling for one minute.",'
           'How to Boil Water to Make It Safe,'
           '" Use a clean pot and the clearest water you can find, letting cloudy water settle first;\n,'
           ' Wait until large bubbles rise steadily from the bottom of the pot and do not stop when you stir;\n,'
           ' At elevations above 6,500 feet, keep the water boiling for three minutes instead of one."\n').encode()


class DocumentsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.site = Site()
        self.addCleanup(self.site.close)
        self.site.files.update({"/army/first.pdf": MANUAL, "/weather/lightning": PAGE,
                                "/archive/erg.pdf": GUIDEBOOK, "/hf/wikihow.csv": WIKIHOW,
                                "/broken/manual.pdf": b"<html>Access denied</html>"})
        url = self.site.url
        self.sources = [
            DocumentSource("survival-manuals", "U.S. government survival and first-aid manuals", "emergency",
                           "Public domain (U.S. government work)", 1.3, (
                               Document("first-aid.pdf", "First Aid (FM 4-25.11)", url + "/army/first.pdf"),
                               Document("erg.pdf", "Emergency Response Guidebook 2024", url + "/refused/erg.pdf",
                                        fallback=url + "/archive/erg.pdf"),  # the site refuses: an archived copy
                           )),
            DocumentSource("risk", "Risk and micromort references", "medical", "Public domain", 1.3, (
                Document("lightning.html", "How Dangerous is Lightning?", url + "/weather/lightning", kind="web"),
            )),
            DocumentSource("wikihow", "wikiHow", "howto", "CC BY-NC-SA 3.0", 1.0, (
                Document("wikihowAll.csv", "wikiHow", url + "/hf/wikihow.csv", kind="wikihow",
                         sha256=hashlib.sha256(WIKIHOW).hexdigest(), size=len(WIKIHOW)),
            )),
        ]

    def fetch(self, sources=None):
        return documents.fetch(self.home, sources or self.sources, log=lambda line: None)

    def build(self):
        build.build(self.home, workers=1, documents_sources=self.sources, log=lambda line: None)
        library = Library(os.path.join(self.home, "library.sqlite"))
        self.addCleanup(library.close)
        return library

    def test_fetches_each_document_falling_back_to_its_archived_copy(self):
        self.assertEqual(self.fetch(), [])
        with open(os.path.join(self.home, "raw", "survival-manuals", "erg.pdf"), "rb") as f:
            self.assertEqual(f.read(), GUIDEBOOK)
        requested = [path for path, _ in self.site.requests]
        self.assertIn("/refused/erg.pdf", requested)
        self.assertIn("/archive/erg.pdf", requested)

    def test_rejects_a_pdf_that_is_not_one(self):
        broken = [DocumentSource("survival-manuals", "Manuals", "emergency", "Public domain", 1.3,
                                 (Document("manual.pdf", "A manual", self.site.url + "/broken/manual.pdf"),))]
        failures = self.fetch(broken)
        self.assertEqual(len(failures), 1)
        self.assertIn("A manual", failures[0])
        self.assertFalse(os.path.exists(os.path.join(self.home, "raw", "survival-manuals", "manual.pdf")))

    def test_an_empty_list_fetches_nothing(self):
        self.assertEqual(documents.fetch(self.home, [], log=lambda line: None), [])
        self.assertFalse(os.path.exists(os.path.join(self.home, "raw")))

    def test_skips_documents_it_already_has(self):
        self.fetch()
        self.site.requests.clear()
        self.assertEqual(self.fetch(), [])
        self.assertEqual(self.site.requests, [])

    def test_builds_documents_into_searchable_articles(self):
        self.fetch()
        library = self.build()
        hit = library.search("tourniquet above the wound")[0]
        self.assertEqual((hit.title, hit.source), ("First Aid (FM 4-25.11)",
                                                  "U.S. government survival and first-aid manuals"))
        self.assertEqual(hit.url, self.site.url + "/army/first.pdf")
        self.assertIn("Public domain", library.article(hit.id).license)
        self.assertEqual(library.search("odds struck by lightning")[0].title, "How Dangerous is Lightning?")

    def test_builds_each_wikihow_row_as_steps(self):
        self.fetch()
        hit = self.build().search("boil water make it safe")[0]
        self.assertEqual(hit.title, "How to Boil Water to Make It Safe")
        self.assertEqual(hit.url, "https://www.wikihow.com/Boil-Water-to-Make-It-Safe")
        self.assertIn("1. Fill a pot with water.", hit.text)
        self.assertIn("3. Keep it boiling for one minute.", hit.text)

    def test_builds_a_wikihow_guide_split_across_rows_as_one_article(self):
        # The dump writes each part of a guide as its own row, not always next to the others, with the part's number
        # glued onto the title, even a title that ends in a number. A guide in one row has no number.
        rows = [("Run cold water over the burn.", "How to Treat a Hand Burn1",
                 "Hold the burned hand under cool running water for at least ten minutes to stop the burning."),
                ("Keep the kettle out of reach.", "How to Childproof a Kitchen",
                 "Push hot drinks and kettles to the back of the counter, where small children cannot reach them."),
                ("Cover the burn loosely.", "How to Treat a Hand Burn2",
                 "Lay sterile gauze or cling film over the burn without wrapping it tightly around the hand."),
                ("Prepare a crash cart.", "How to Survive Turning 181",
                 "Gather snacks, water and a blanket the night before your eighteenth birthday party begins."),
                ("See a doctor for a deep burn.", "How to Treat a Hand Burn3",
                 "Get medical care at once if the burn is larger than your palm, white, charred or leathery."),
                ("Pace yourself.", "How to Survive Turning 182",
                 "Drink a glass of water between celebrations and leave the party before you feel exhausted."),
                ("Take your vitamin with food.", "How to Take Vitamin B12",
                 "Swallow the tablet with breakfast, since a full stomach helps the body absorb the vitamin better.")]
        os.makedirs(os.path.join(self.home, "raw", "wikihow"))
        with open(os.path.join(self.home, "raw", "wikihow", "wikihowAll.csv"), "w", encoding="utf-8") as f:
            f.write("headline,title,text\n" + "".join(f'"\n{head}",{title}," {" ".join([text] * 3)}"\n'
                                                      for head, title, text in rows))
        library = self.build()
        self.assertEqual(sorted(title for (title,) in library.db.execute("SELECT title FROM articles")), [
            "How to Childproof a Kitchen", "How to Survive Turning 18", "How to Take Vitamin B12",
            "How to Treat a Hand Burn"])
        burn = library.article(library.search("burned hand cold water")[0].id)
        self.assertEqual((burn.title, burn.url), ("How to Treat a Hand Burn",
                                                  "https://www.wikihow.com/Treat-a-Hand-Burn"))
        self.assertLess(burn.text.index("## Section 1 of 3\n\n1. Run cold water over the burn."),
                        burn.text.index("## Section 2 of 3\n\n1. Cover the burn loosely."))
        self.assertLess(burn.text.index("## Section 2 of 3"),
                        burn.text.index("## Section 3 of 3\n\n1. See a doctor for a deep burn."))
        birthday = library.article(library.search("eighteenth birthday party")[0].id).text
        self.assertIn("## Section 2 of 2\n\n1. Pace yourself.", birthday)
        kitchen = library.article(library.search("kettle out of reach")[0].id).text
        self.assertTrue(kitchen.startswith("1. Keep the kettle out of reach."))

    def test_rebuilds_a_source_when_its_documents_change(self):
        self.fetch()
        self.build()
        os.remove(os.path.join(self.home, "raw", "risk", "lightning.html"))
        self.site.files["/weather/lightning"] = PAGE.replace(b"one in a million", b"one in 1.2 million")
        self.fetch()
        self.assertIn("1.2 million", self.build().search("odds struck by lightning")[0].text)


if __name__ == "__main__":
    unittest.main()
