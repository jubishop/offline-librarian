"""Downloading Kiwix books: catalog lookup, mirrors, resuming, and checksums, against a local web server."""
import offline  # noqa: F401  (tests never reach the internet)
import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from librarian import kiwix

WATER = b"water " * 50_000
MEDICINE = b"medicine " * 40_000


class Site:
    """A local stand-in for the Kiwix catalog and its mirrors. Paths map to bytes, or to a failure mode."""

    def __init__(self):
        self.files, self.requests = {}, []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                site.requests.append((self.path, self.headers.get("Range")))
                body = site.files.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                cut = None
                if isinstance(body, tuple):  # ("drop", data): send half of it once, then hang up
                    mode, body = body
                    if mode == "drop":
                        site.files[self.path] = body
                        cut = len(body) // 2
                start = 0
                if self.headers.get("Range"):
                    start = int(self.headers["Range"].removeprefix("bytes=").removesuffix("-"))
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body) - start))
                self.end_headers()
                self.wfile.write(body[start:cut] if cut else body[start:])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def book(self, name, flavour, data, mirrors=("/m1",), checksum=None, edition="2026-10"):
        """Publish a book: its catalog entry, its Metalink file, and its file on each mirror."""
        filename = f"{name}_{flavour or 'all'}_{edition}.zim"
        urls = "".join(f'<url priority="{n + 1}">{self.url}{m}/{filename}</url>'
                       for n, m in enumerate(mirrors))
        self.files[f"/meta/{filename}.meta4"] = f"""<?xml version="1.0" encoding="UTF-8"?>
<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="{filename}">
<size>{len(data)}</size><hash type="md5">0</hash>
<hash type="sha-256">{checksum or hashlib.sha256(data).hexdigest()}</hash>{urls}</file></metalink>""".encode()
        for m in mirrors:
            self.files.setdefault(f"{m}/{filename}", data)
        return filename, f"""<entry><name>{name}</name><flavour>{flavour}</flavour>
<updated>{edition}-20T00:00:00Z</updated>
<link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim"
 href="{self.url}/meta/{filename}.meta4" length="{len(data)}" /></entry>"""

    def catalog(self, *entries):
        self.files["/catalog"] = ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
                                  + "".join(entries) + "</feed>").encode()
        return self.url + "/catalog"


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = tmp.name
        self.lines = []

    def fetch(self, sources, catalog):
        return kiwix.fetch(sources, self.folder, catalog_url=catalog, log=self.lines.append)

    def read(self, filename):
        with open(os.path.join(self.folder, filename), "rb") as f:
            return f.read()

    def test_downloads_each_book_and_records_it(self):
        water, water_entry = self.site.book("zimgit-water_en", "", WATER)
        medicine, medicine_entry = self.site.book("wikem_en_all", "nopic", MEDICINE)
        failures = self.fetch([("zimgit-water_en", ""), ("wikem_en_all", "nopic")],
                              self.site.catalog(water_entry, medicine_entry))
        self.assertEqual(failures, [])
        self.assertEqual(self.read(water), WATER)
        self.assertEqual(self.read(medicine), MEDICINE)
        with open(os.path.join(self.folder, "manifest.json")) as f:
            manifest = json.load(f)
        self.assertEqual(manifest["wikem_en_all nopic"]["file"], medicine)
        self.assertEqual(manifest["wikem_en_all nopic"]["sha256"], hashlib.sha256(MEDICINE).hexdigest())
        self.assertEqual(manifest["zimgit-water_en"]["updated"], "2026-10-20")

    def test_picks_the_requested_flavour(self):
        _, nopic = self.site.book("wikem_en_all", "nopic", MEDICINE)
        _, maxi = self.site.book("wikem_en_all", "maxi", WATER)
        self.assertEqual(self.fetch([("wikem_en_all", "nopic")], self.site.catalog(maxi, nopic)), [])
        self.assertEqual(self.read("wikem_en_all_nopic_2026-10.zim"), MEDICINE)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "wikem_en_all_maxi_2026-10.zim")))

    def test_resumes_a_partial_download(self):
        filename, entry = self.site.book("zimgit-water_en", "", WATER)
        with open(os.path.join(self.folder, filename + ".part"), "wb") as f:
            f.write(WATER[:100_000])
        self.assertEqual(self.fetch([("zimgit-water_en", "")], self.site.catalog(entry)), [])
        self.assertEqual(self.read(filename), WATER)
        self.assertIn((f"/m1/{filename}", "bytes=100000-"), self.site.requests)

    def test_picks_up_again_when_the_connection_drops(self):
        filename, entry = self.site.book("zimgit-water_en", "", WATER)
        self.site.files[f"/m1/{filename}"] = ("drop", WATER)
        self.assertEqual(self.fetch([("zimgit-water_en", "")], self.site.catalog(entry)), [])
        self.assertEqual(self.read(filename), WATER)
        self.assertIn((f"/m1/{filename}", f"bytes={len(WATER) // 2}-"), self.site.requests)

    def test_falls_back_to_the_next_mirror(self):
        filename, entry = self.site.book("zimgit-water_en", "", WATER, mirrors=("/down", "/m2"))
        del self.site.files[f"/down/{filename}"]
        self.assertEqual(self.fetch([("zimgit-water_en", "")], self.site.catalog(entry)), [])
        self.assertEqual(self.read(filename), WATER)

    def test_rejects_a_file_that_fails_its_checksum(self):
        filename, entry = self.site.book("zimgit-water_en", "", WATER, checksum="0" * 64)
        failures = self.fetch([("zimgit-water_en", "")], self.site.catalog(entry))
        self.assertEqual(len(failures), 1)
        self.assertIn("checksum", failures[0])
        self.assertEqual(os.listdir(self.folder), [])

    def test_reports_a_book_missing_from_the_catalog_and_gets_the_rest(self):
        filename, entry = self.site.book("zimgit-water_en", "", WATER)
        failures = self.fetch([("gardenology.org_en_all", ""), ("zimgit-water_en", "")], self.site.catalog(entry))
        self.assertEqual(len(failures), 1)
        self.assertIn("gardenology.org_en_all", failures[0])
        self.assertEqual(self.read(filename), WATER)

    def test_skips_a_book_it_already_has(self):
        filename, entry = self.site.book("zimgit-water_en", "", WATER)
        catalog = self.site.catalog(entry)
        self.fetch([("zimgit-water_en", "")], catalog)
        self.site.requests.clear()
        self.assertEqual(self.fetch([("zimgit-water_en", "")], catalog), [])
        self.assertNotIn(f"/m1/{filename}", [path for path, _ in self.site.requests])
        self.assertEqual(self.read(filename), WATER)


if __name__ == "__main__":
    unittest.main()
