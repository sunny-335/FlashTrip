"""slug 契约：中文→拼音、标点转换、截断兜底、随机后缀、existing 去重。"""
from __future__ import annotations

import re

from app.services import slug


def test_chinese_to_pinyin():
    assert slug.to_slug("苏州三日游") == "suzhousanriyou"


def test_non_chinese_and_punctuation():
    assert slug.to_slug("Hello World 2024") == "hello-world-2024"
    assert slug.to_slug("A_B!C") == "a-b-c"


def test_empty_falls_back_to_trip():
    assert slug.to_slug("") == "trip"
    assert slug.to_slug("!!!") == "trip"


def test_truncate_to_40():
    assert len(slug.to_slug("a" * 60)) == 40


def test_folder_name_has_4_char_lowercase_suffix():
    name = slug.trip_folder_name("苏州三日游")
    assert re.fullmatch(r"suzhousanriyou-[a-z0-9]{4}", name), name


def test_existing_triggers_retry(monkeypatch):
    sequence = iter(["aaaa", "bbbb"])
    monkeypatch.setattr(slug, "_random_suffix", lambda *args, **kwargs: next(sequence))
    name = slug.trip_folder_name("苏州三日游", existing={"suzhousanriyou-aaaa"})
    assert name == "suzhousanriyou-bbbb"
