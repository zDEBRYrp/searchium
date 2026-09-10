"""
i18n API endpoint - serves translation files
"""

import json
import os
from typing import Dict

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/i18n", tags=["i18n"])

_i18n_cache: Dict[str, Dict] = {}
_i18n_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "i18n")


def _load_translations(lang: str) -> Dict:
    if lang in _i18n_cache:
        return _i18n_cache[lang]

    path = os.path.join(_i18n_dir, f"{lang}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    _i18n_cache[lang] = data
    return data


@router.get("/available")
def get_available_languages():
    langs = []
    for f in os.listdir(_i18n_dir):
        if f.endswith(".json"):
            langs.append(f.replace(".json", ""))
    return {"languages": langs}


@router.get("/{lang}")
def get_translations(lang: str):
    return _load_translations(lang)
