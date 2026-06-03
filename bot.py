from __future__ import annotations

import hashlib
import html
import io
import logging
import mimetypes
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import urllib3
except Exception:  # pragma: no cover - urllib3 comes with requests in normal installs.
    urllib3 = None

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - handled during startup with a clear error.
    BeautifulSoup = None

try:
    import pikepdf
except Exception:
    pikepdf = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except Exception:
    Image = ImageDraw = ImageFont = ImageOps = None


LOGGER = logging.getLogger("improved_bot")

URL_RE = re.compile(r"""(?ix)\b(https?://[^\s<>"')\]]+)""")
TRAILING_URL_PUNCT = ".,;:!?)]]}"

IMAGE_ATTRS = (
    "src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-orig-file",
    "data-medium-file",
    "data-large-file",
    "data-url",
)
BAD_IMAGE_HINTS = ("placeholder", "spacer", "blank.gif", "lazyload", "loading.gif")
MEDIA_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

BRAND_NAME = os.environ.get("BRAND_NAME", "POSITRON ACADEMY").strip() or "POSITRON ACADEMY"
BRAND_ADDRESS = (
    os.environ.get("BRAND_ADDRESS", "चौधरी हॉस्पिटल के पास, पांसल चौराहा, भीलवाड़ा").strip()
    or "चौधरी हॉस्पिटल के पास, पांसल चौराहा, भीलवाड़ा"
)
BRAND_ADDRESS_FALLBACK = "Chaudhary Hospital ke paas, Pansal Chauraha, Bhilwara"
BRAND_CONTACT = os.environ.get("BRAND_CONTACT", "8104894648").strip() or "8104894648"
BRAND_SKIP_TYPES = {"image/gif", "image/svg+xml"}

SPAM_TEXT_HINTS = (
    "betting",
    "casino",
    "aviator",
    "paid promo",
    "paid promotion",
    "sponsored",
    "sponsor",
    "prediction game",
    "earn money",
    "promo code",
    "refer and earn",
)
HARD_SKIP_PHRASES = ("शिक्षा विभाग समाचार",)
DEFAULT_SOURCE_PAGE_HOSTS = ("indianaukrihelp.com",)
SPAM_HOST_HINTS = (
    "1xbet",
    "bet365",
    "parimatch",
    "stake.com",
    "dream11",
    "casino",
    "aviator",
)
SUSPICIOUS_INVITE_PATTERNS = (
    "t.me/+",
    "telegram.me/+",
