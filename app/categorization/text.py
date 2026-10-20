from __future__ import annotations

import re
import unicodedata

_PREFIXES = re.compile(r"^(pg \*|pag\*|mp \*|mercadopago \*|ifd\*|ec \*|pp \*|paypal \*|dl \*|ebn \*|htm\*|sumup \*|picpay \*)")
_NOISE = re.compile(r"[\d\W_]+")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str | None) -> str:
    """minúsculas, sem acento, espaços colapsados."""
    return re.sub(r"\s+", " ", strip_accents((s or "").lower())).strip()


def merchant_alias(description: str | None) -> str | None:
    """Chave estável de comerciante a partir da descrição (ex.: 'UBER *TRIP 1234' → 'uber trip')."""
    d = _PREFIXES.sub("", norm(description))
    d = _NOISE.sub(" ", d).strip()
    words = [w for w in d.split() if len(w) > 1][:3]
    return " ".join(words) or None


def counterparty_from_description(description: str | None) -> str | None:
    """Nubank e outros: 'Transferência enviada|FULANO DE TAL' → 'FULANO DE TAL'."""
    if description and "|" in description:
        return description.split("|", 1)[1].strip() or None
    return None
