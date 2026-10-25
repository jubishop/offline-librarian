"""What the library is built from: Survival LLM's full personal source list (see docs/design.md#sources).

The labels, topics, licenses and skipped paths are adapted from Survival LLM's library/build_library.py
(MIT License, Copyright (c) 2026 Ronny Fernandez; see LICENSE.survival-llm).
"""
from dataclasses import dataclass

CC_BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/"
CC_BY_NC_SA = "https://creativecommons.org/licenses/by-nc-sa/3.0/"
US_GOV = "Public domain (U.S. government work)"
SE_LICENSE = "CC BY-SA 2.5, 3.0 or 4.0 by post date, the authors named with each post https://stackoverflow.com/help/licensing"
# Translated copies of pages ("Page/tr" in WikEM) and sites' non-English sections.
FOREIGN_SECTIONS = r"/(es|spanish|espanol|languages|translations)(/|$)"


@dataclass(frozen=True)
class Source:
    name: str          # the Kiwix book name
    flavour: str       # the Kiwix flavour ("nopic", "maxi"), or ""
    key: str           # short, stable name in the library
    label: str         # how answers name the source
    topic: str         # medical, emergency, howto, repair or encyclopedia
    kind: str          # how its pages are laid out: wiki, se (Stack Exchange), web or pdf
    url: str           # prepended to an entry's path to make its web address
    license: str
    weight: float = 1.0      # search ranking boost: 1.3 for official and clinical sources, 1.15 for Wikipedia
    skip: str = ""     # regular expression for entry paths to leave out


def _se(site, label, topic):
    return Source(f"{site}.stackexchange.com_en_all", "", f"se-{site}", f"{label} (Stack Exchange)", topic, "se",
                  f"https://{site}.stackexchange.com/", SE_LICENSE)


# Smallest and most survival-focused first, so the early books are ready to build while the big ones download.
# WikiMed comes before Wikipedia, so medical articles keep WikiMed as their source.
# Survival LLM also lists gardenology.org_en_all, which was missing from the Kiwix catalog on 2026-10-25.
SOURCES = [
    Source("zimgit-water_en", "", "water", "Water Treatment Library", "emergency", "pdf", "",
           "Mixed: documents from many publishers", weight=1.3),
    Source("zimgit-food-preparation_en", "", "food-prep", "Food for Preppers", "emergency", "pdf", "",
           "Mixed: documents from many publishers", weight=1.3),
    Source("zimgit-medicine_en", "", "medical-library", "Medical Library", "medical", "pdf", "",
           "Mixed: documents from many publishers", weight=1.3),
    Source("zimgit-knots_en", "", "knots", "Library of Knots", "howto", "pdf", "",
           "Mixed: documents from many publishers"),
    Source("zimgit-post-disaster_en", "", "post-disaster", "Post Disaster Resource Library", "emergency", "pdf", "",
           "Mixed: documents from many publishers", weight=1.3),
    Source("irp.fas.org_en_military-medicine", "", "military-medicine", "Military medicine manuals", "medical", "pdf",
           "https://", US_GOV, weight=1.3),
    Source("nhs.uk_en_medicines", "", "nhs-medicines", "UK Medicines A to Z (public sector information)", "medical",
           "web", "https://", "Contains public sector information licensed under the Open Government Licence v3.0 "
           "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/", weight=1.3),
    Source("wikem_en_all", "nopic", "wikem", "WikEM emergency medicine", "medical", "wiki", "https://wikem.org/wiki/",
           f"CC BY-SA 4.0, WikEM contributors {CC_BY_SA}", weight=1.3, skip=r"/[a-z]{2}(-[a-z]+)?$"),
    Source("wwwnc.cdc.gov_en_all", "", "cdc-travel", "CDC Travelers' Health", "medical", "web", "https://",
           f"{US_GOV}, CDC (the printed Yellow Book is published by Oxford University Press)", weight=1.3,
           skip=FOREIGN_SECTIONS),
    Source("usda-2015_en", "", "usda-canning", "USDA Complete Guide to Home Canning", "emergency", "web",
           "https://nchfp.uga.edu/resources/category/usda-guide#", f"{US_GOV}, USDA", weight=1.3),
    Source("wikiciv_en_all", "maxi", "wikiciv", "WikiCiv (rebuilding technology)", "howto", "wiki",
           "https://wikiciv.org/wiki/", f"CC BY-SA 4.0, WikiCiv contributors {CC_BY_SA}"),
    _se("outdoors", "The Great Outdoors Q&A", "howto"),
    _se("cooking", "Cooking Q&A", "howto"),
    _se("lifehacks", "Lifehacks Q&A", "howto"),
    _se("sustainability", "Sustainable Living Q&A", "howto"),
    _se("ham", "Amateur Radio Q&A", "howto"),
    _se("medicalsciences", "Medical Sciences Q&A", "medical"),
    _se("gardening", "Gardening Q&A", "howto"),
    _se("diy", "Home Improvement Q&A", "repair"),
    _se("mechanics", "Motor Vehicle Repair Q&A", "repair"),
    _se("pets", "Pets Q&A", "howto"),
    Source("appropedia_en_all", "maxi", "appropedia", "Appropedia", "howto", "wiki", "https://www.appropedia.org/",
           f"CC BY-SA 3.0 or 4.0 (per page), Appropedia contributors {CC_BY_SA}"),
    Source("energypedia_en_all", "nopic", "energypedia", "Energypedia (solar, batteries, stoves)", "howto", "wiki",
           "https://energypedia.info/wiki/", f"CC BY-SA 3.0 or 4.0 (per page), Energypedia contributors {CC_BY_SA}"),
    Source("wikipedia_en_medicine", "nopic", "wikimed", "WikiMed (Wikipedia medicine)", "medical", "wiki",
           "https://en.wikipedia.org/wiki/", f"CC BY-SA 4.0, Wikipedia contributors {CC_BY_SA}", weight=1.15),
    Source("medlineplus.gov_en_all", "", "medlineplus", "MedlinePlus (NIH)", "medical", "web", "https://",
           f"{US_GOV}, U.S. National Library of Medicine; its encyclopedia and drug pages are licensed to NLM by "
           "A.D.A.M., ASHP and Natural Medicines", weight=1.3, skip=FOREIGN_SECTIONS),
    Source("ready.gov_en_all", "", "ready-gov", "Ready.gov (FEMA)", "emergency", "web", "https://",
           f"{US_GOV}, FEMA", weight=1.3, skip=FOREIGN_SECTIONS),
    Source("ifixit_en_all", "", "ifixit", "iFixit repair guides", "repair", "web", "https://www.ifixit.com/",
           f"CC BY-NC-SA 3.0 (non-commercial), iFixit guide authors {CC_BY_NC_SA}"),
    Source("wikipedia_en_top1m", "nopic", "wikipedia", "Wikipedia", "encyclopedia", "wiki",
           "https://en.wikipedia.org/wiki/", f"CC BY-SA 4.0, Wikipedia contributors {CC_BY_SA}", weight=1.15),
]

KIWIX = [(source.name, source.flavour) for source in SOURCES]
# Sources whose articles can repeat in another: a title already in the library is skipped.
SAME_ARTICLES = {"wikimed", "wikipedia"}
