"""Trust scoring (spec section 27): HIGH / MEDIUM / LOW / UNKNOWN per source.

Domain-based classification, deliberately conservative:
- HIGH: recognized manufacturer domains (primary technical authority)
- MEDIUM: authorized distributors/marketplaces (real data, not the maker)
- LOW: forums, wikis, blogs (community knowledge)
- UNKNOWN: anything not recognized - must not be presented as authoritative
"""
from __future__ import annotations

from urllib.parse import urlparse

from core.models import Confidence

MANUFACTURER_DOMAINS = (
    "sew-eurodrive", "sew", "nord", "nord-drivesystems", "lenze", "abb", "siemens",
    "weg", "rockwellautomation", "ab.com", "mitsubishi", "bonfiglioli", "motovario",
    "bauer-gear", "boschrexroth", "parker", "leroy-somer", "nidec", "regalrexnord",
    "vemat", "sicmemotori", "schneider-electric", "beckhoff", "phoenixcontact",
    "wago", "festo", "smc", "skf", "schaeffler", "fag", "nsk", "timken", "ntn",
    "gates", "optibelt", "continental", "dana", "igus", "ebm-papst", "danfoss",
    "fanuc", "yaskawa", "delta", "omron", "pilz", "sick", "balluff", "ifm",
    "turck", "pepperl-fuchs",
)

DISTRIBUTOR_DOMAINS = (
    "rs-online", "rscomponents", "farnell", "newark", "digikey", "mouser",
    "tme", "radiospares", "distrelec", "conrad", "kellysearch", "cdiscount",
    "amazon", "ebay", "alibaba", "aliexpress", "misumi",
)

LOW_TRUST_MARKERS = (
    "forum", "reddit", "wikipedia", "stackexchange", "stackoverflow", "quora",
    "blogspot", "wordpress.com", "medium.com", "pinterest", "facebook",
    "twitter", "x.com",
)


def trust_for_url(url: str) -> Confidence:
    """Classify a URL's trust level from its domain."""
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return Confidence.UNKNOWN
    if not host:
        return Confidence.UNKNOWN

    for marker in LOW_TRUST_MARKERS:
        if marker in host:
            return Confidence.LOW
    for dom in MANUFACTURER_DOMAINS:
        if dom in host:
            return Confidence.HIGH
    for dom in DISTRIBUTOR_DOMAINS:
        if dom in host:
            return Confidence.MEDIUM
    return Confidence.UNKNOWN
