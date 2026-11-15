"""Minimal HTML helpers for the sign-in pages and the homework contents.

Only the standard library is used: the sign-in pages are simple server-rendered forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

_CAPTCHA_MARKERS = re.compile(r'id="captchetat"|captchaFormulaireExtInput|g-recaptcha|h-captcha', re.I)


@dataclass(slots=True)
class FormInput:
    """An input of a form."""

    name: str
    type: str
    value: str
    id: str | None = None


@dataclass(slots=True)
class Form:
    """A form of a page, with its inputs and named submit buttons."""

    action: str
    method: str
    id: str | None
    inputs: list[FormInput] = field(default_factory=list)
    buttons: list[tuple[str, str]] = field(default_factory=list)

    def values(self) -> dict[str, str]:
        """Default values of the non-radio inputs (what a browser would send untouched)."""
        return {
            i.name: i.value for i in self.inputs if i.type not in ("radio", "checkbox", "submit", "button")
        }

    def has_type(self, input_type: str) -> bool:
        """Whether the form has an input of this type."""
        return any(i.type == input_type for i in self.inputs)

    @property
    def is_auto_submit(self) -> bool:
        """A form made of hidden fields only, normally posted by JavaScript (SAML, Shibboleth)."""
        visible = [i for i in self.inputs if i.type not in ("hidden", "submit", "button")]
        return self.method == "post" and not visible and any(i.type == "hidden" for i in self.inputs)


@dataclass(slots=True)
class RadioChoice:
    """A radio button with its label and the legend of its fieldset."""

    name: str
    value: str
    label: str
    category: str | None


@dataclass(slots=True)
class Page:
    """What the sign-in logic needs to know about a page."""

    title: str
    forms: list[Form]
    radios: list[RadioChoice]
    has_captcha: bool


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[Form] = []
        self.title = ""
        self._in_title = False
        self._form: Form | None = None
        self._labels: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []
        self._legend: str | None = None
        self._in_legend = False
        self._legend_text: list[str] = []
        self._radios: list[tuple[str, str, str | None, str | None]] = []  # name, value, id, legend

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "form":
            self._form = Form(
                action=a.get("action", ""), method=a.get("method", "get").lower(), id=a.get("id") or None
            )
            self.forms.append(self._form)
        elif tag == "fieldset":
            self._legend = None
        elif tag == "legend":
            self._in_legend = True
            self._legend_text = []
        elif tag == "label":
            self._label_for = a.get("for") or None
            self._label_text = []
        elif tag == "input" and self._form is not None and a.get("name"):
            itype = a.get("type", "text").lower()
            self._form.inputs.append(FormInput(a["name"], itype, a.get("value", ""), a.get("id") or None))
            if itype == "radio":
                self._radios.append((a["name"], a.get("value", ""), a.get("id") or None, self._legend))
        elif (
            tag == "button"
            and self._form is not None
            and a.get("name")
            and a.get("type", "submit").lower() == "submit"
        ):
            self._form.buttons.append((a["name"], a.get("value", "")))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "form":
            self._form = None
        elif tag == "fieldset":
            self._legend = None
        elif tag == "legend":
            self._in_legend = False
            self._legend = _clean(" ".join(self._legend_text)) or None
        elif tag == "label" and self._label_for:
            self._labels[self._label_for] = _clean(" ".join(self._label_text))
            self._label_for = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_legend:
            self._legend_text.append(data)
        if self._label_for:
            self._label_text.append(data)

    def radios(self) -> list[RadioChoice]:
        return [
            RadioChoice(name, value, self._labels.get(rid or "", value), legend)
            for name, value, rid, legend in self._radios
        ]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_page(html: str) -> Page:
    """Parse the forms, labelled radio buttons and captcha markers of a page."""
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    return Page(
        title=_clean(parser.title),
        forms=parser.forms,
        radios=parser.radios(),
        has_captcha=bool(_CAPTCHA_MARKERS.search(html)),
    )


_BLOCK_TAGS = re.compile(r"<\s*(br|/p|/div|/li|/h[1-6]|/tr)\b[^>]*>", re.I)
_LIST_ITEM = re.compile(r"<\s*li\b[^>]*>", re.I)
_DROP = re.compile(r"<\s*(script|style|head)\b.*?<\s*/\s*\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(html: str | None) -> str:
    """Turn a small HTML fragment (homework, message) into plain text with line breaks."""
    if not html:
        return ""
    text = _DROP.sub("", html)
    text = _LIST_ITEM.sub("\n• ", text)
    text = _BLOCK_TAGS.sub("\n", text)
    text = unescape(_TAG.sub("", text)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line.startswith("•") and out and not out[-1]:
            out.pop()  # no blank line before a list item
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()
