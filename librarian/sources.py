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
# Ready.gov repeats most pages under language prefixes (www.ready.gov/de/node/11963), mostly in English with a
# different language menu: 1,614 of its 2,320 pages on 2026-10-25.
READY_GOV_LANGUAGES = r"^www\.ready\.gov/[a-z]{2}(-[a-z]+)?/"


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
           f"{US_GOV}, FEMA", weight=1.3, skip=FOREIGN_SECTIONS + "|" + READY_GOV_LANGUAGES),
    Source("ifixit_en_all", "", "ifixit", "iFixit repair guides", "repair", "web", "https://www.ifixit.com/",
           f"CC BY-NC-SA 3.0 (non-commercial), iFixit guide authors {CC_BY_NC_SA}"),
    Source("wikipedia_en_top1m", "nopic", "wikipedia", "Wikipedia", "encyclopedia", "wiki",
           "https://en.wikipedia.org/wiki/", f"CC BY-SA 4.0, Wikipedia contributors {CC_BY_SA}", weight=1.15),
]

KIWIX = [(source.name, source.flavour) for source in SOURCES]
# Sources whose articles can repeat in another: a title already in the library is skipped.
SAME_ARTICLES = {"wikimed", "wikipedia"}


# ---------- sources that aren't Kiwix books ----------
# The documents, their addresses and the Internet Archive fallbacks are adapted from Survival LLM's
# library/fetch_manuals.py and library/fetch_risk.py (MIT License, Copyright (c) 2026 Ronny Fernandez; see
# LICENSE.survival-llm). Its copies of Wikipedia's risk articles are left out: this library has Wikipedia itself.

ARCHIVE = "https://web.archive.org/web/2026id_/"  # the Internet Archive's raw copy of a page, for sites that refuse
ARMY = "https://armypubs.army.mil/epubs/DR_pubs/DR_a/"
WHO = "https://iris.who.int/server/api/core/bitstreams/"


@dataclass(frozen=True)
class Document:
    file: str          # its name in raw/<source key>/
    title: str
    url: str
    kind: str = "pdf"  # pdf, web, life-table (the SSA table, rewritten as lines) or wikihow (the CSV dump)
    fallback: str = ""  # another address for the same file, for sites that refuse scripted downloads
    sha256: str = ""   # when the publisher gives one
    size: int = 0


@dataclass(frozen=True)
class DocumentSource:
    key: str
    label: str
    topic: str
    license: str
    weight: float
    documents: tuple


def _archived(file, title, url, kind="pdf", fallback=None):
    return Document(file, title, url, kind, fallback or ARCHIVE + url)


DOCUMENTS = [
    DocumentSource("survival-manuals", "U.S. government survival and first-aid manuals", "emergency",
                   f"{US_GOV}, except Nuclear War Survival Skills (1986 additions copyright Cresson H. Kearny, "
                   "reproduced with his notice) and the Emergency Response Guidebook 2024 (reproduction permitted by "
                   "the participating governments, not for resale)", 1.3, (
        _archived("afh10-644.pdf", "USAF AFH 10-644: SERE Operations (survival, evasion, field medicine)",
                  "https://static.e-publishing.af.mil/production/1/af_a3/publication/afh10-644/afh10-644.pdf",
                  fallback="https://web.archive.org/web/2025id_/https://static.e-publishing.af.mil/production/1/af_a3/"
                           "publication/afh10-644/afh10-644.pdf"),
        _archived("atp3-50-21.pdf", "US Army ATP 3-50.21: Survival", ARMY + "pdf/web/ARN12086_ATP%203-50x21%20FINAL%20WEB%202.pdf"),
        _archived("atp4-02-11.pdf", "US Army ATP 4-02.11: Casualty Response, Tactical Combat Casualty Care and First "
                  "Aid (2026)", ARMY + "ARN46159-ATP_4-02.11-000-WEB-1.pdf"),
        _archived("tc21-3.pdf", "US Army TC 21-3: Cold Weather Survival and Operations", ARMY + "ARN45217-TC_21-3-000-WEB-1.pdf"),
        _archived("atp4-25-12.pdf", "US Army ATP 4-25.12: Unit Field Sanitation", ARMY + "ARN44577-ATP_4-25.12-002-WEB-3.pdf"),
        _archived("tbmed577.pdf", "US Army TB MED 577: Sanitary Control and Surveillance of Field Water Supplies",
                  ARMY + "pdf/web/tbmed577.pdf"),
        _archived("tbmed507.pdf", "US Army TB MED 507: Heat Stress Control and Heat Casualty Management",
                  ARMY + "ARN43608-TB_MED_507-001-WEB-2.pdf"),
        _archived("nwss.pdf", "Nuclear War Survival Skills (Cresson Kearny, ORNL-5037, 1979)",
                  "https://www.osti.gov/servlets/purl/814213"),
        _archived("are-you-ready.pdf", "FEMA: Are You Ready? An In-Depth Guide to Citizen Preparedness",
                  "https://www.ready.gov/sites/default/files/2021-11/are-you-ready-guide.pdf"),
        _archived("cert-basic.pdf", "FEMA CERT Basic Training Participant Manual",
                  "https://www.ready.gov/sites/default/files/2019.CERT_.Basic_.PM_FINAL_508c.pdf"),
        _archived("erg2024.pdf", "Emergency Response Guidebook 2024 (hazardous materials)",
                  "https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/2024-04/ERG2024-Eng-Web-a.pdf",
                  fallback="https://web.archive.org/web/20240806051758id_/https://www.phmsa.dot.gov/sites/phmsa.dot.gov/"
                           "files/2024-04/ERG2024-Eng-Web-a.pdf"),
        _archived("prolonged-casualty-care.pdf", "Joint Trauma System: Prolonged Casualty Care Guidelines (2021)",
                  "https://jts.health.mil/assets/docs/cpgs/Prolonged_Casualty_Care_Guidelines_21_Dec_2021_ID91v1.1.pdf"),
    )),
    DocumentSource("first-aid-guides", "IFRC and WHO first-aid and emergency care guides", "medical",
                   "IFRC guidelines: non-commercial use with acknowledgement. WHO publications: CC BY-NC-SA 3.0 IGO "
                   "https://creativecommons.org/licenses/by-nc-sa/3.0/igo/ (WHO does not endorse this library)", 1.3, (
        _archived("ifrc-2020.pdf", "IFRC International First Aid, Resuscitation and Education Guidelines 2020",
                  "https://www.ifrc.org/sites/default/files/2022-02/EN_GFARC_GUIDELINES_2020.pdf"),
        _archived("who-basic-emergency-care.pdf", "WHO-ICRC Basic Emergency Care (2018)",
                  WHO + "63432b9f-8808-44c5-9692-cea717c0cbda/content"),
        _archived("who-childbirth.pdf", "WHO: Managing Complications in Pregnancy and Childbirth (2017)",
                  WHO + "3bda1306-da5d-487d-b2ad-aff995112a7a/content"),
        _archived("who-drinking-water.pdf", "WHO: Guidelines for Drinking-water Quality (4th ed., 2022)",
                  WHO + "69c17edd-ee26-425b-9d34-33799377e886/content"),
    )),
    DocumentSource("risk", "Risk and micromort references", "medical",
                   "U.S. government statistics (SSA, CDC, NHTSA, NWS): public domain", 1.3, (
        _archived("ssa-life-table.html", "Actuarial Life Table: chance of dying within a year at each age (Social "
                  "Security, 2023)", "https://www.ssa.gov/oact/STATS/table4c6.html", kind="life-table"),
        _archived("cdc-mortality-2024.pdf", "Mortality in the United States, 2024 (CDC NCHS Data Brief 548)",
                  "https://www.cdc.gov/nchs/data/databriefs/db548.pdf"),
        _archived("cdc-leading-causes-2024.pdf", "Deaths: Leading Causes for 2024, death rates by cause and age (CDC "
                  "NCHS)", "https://www.cdc.gov/nchs/data/nvsr/nvsr75/nvsr75-07.pdf"),
        _archived("nhtsa-crashes-2024.pdf", "Overview of Motor Vehicle Traffic Crashes in 2024 (NHTSA), deaths per mile "
                  "driven", "https://crashstats.nhtsa.dot.gov/Api/Public/ViewPublication/813791"),
        _archived("nws-lightning-odds.html", "How Dangerous is Lightning? Odds of being struck (National Weather "
                  "Service)", "https://www.weather.gov/safety/lightning-odds", kind="web"),
    )),
    # The 2018 text dump (Koupaee and Wang); its size and SHA-256 are Hugging Face's, checked on 2026-10-25.
    DocumentSource("wikihow", "wikiHow", "howto", f"CC BY-NC-SA 3.0 (non-commercial), wikiHow contributors {CC_BY_NC_SA}",
                   1.0, (
        Document("wikihowAll.csv", "wikiHow", "https://huggingface.co/datasets/Lajvi/wikihowAll/resolve/main/"
                 "wikihowAll.csv", kind="wikihow",
                 sha256="8ebf5bd485275af895aa83ea3e55c416fe76aa4fefc58e0b9e6d344852bde5aa", size=619172672),
    )),
]
