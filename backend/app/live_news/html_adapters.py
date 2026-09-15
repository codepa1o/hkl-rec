from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import html as lxml_html  # type: ignore[import-untyped]
from lxml.html import HtmlElement  # type: ignore[import-untyped]

from backend.app.live_news.content_policy import HtmlAdapterName
from backend.app.live_news.content_types import ContentAcquisitionError


def _class_predicate(class_name: str) -> str:
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {class_name} ')"


def _selector_xpath(selector: str, *, relative: bool) -> str:
    prefix = ".//" if relative else "//"
    parts = selector.strip().split()
    expressions: list[str] = []
    for part in parts:
        if part.startswith("#"):
            expressions.append(f"*[@id='{part[1:]}']")
        elif part.startswith("."):
            classes = [value for value in part.split(".") if value]
            predicates = " and ".join(_class_predicate(value) for value in classes)
            expressions.append(f"*[{predicates}]")
        else:
            expressions.append(part)
    return prefix + "//".join(expressions)


def _host_allowed(host: str, domains: tuple[str, ...]) -> bool:
    normalized = host.rstrip(".").lower()
    return any(normalized == domain or normalized.endswith(f".{domain}") for domain in domains)


def _normalize_url(value: str, base_url: str, domains: tuple[str, ...]) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    candidate = f"https:{candidate}" if candidate.startswith("//") else urljoin(base_url, candidate)
    parsed = urlsplit(candidate)
    host = parsed.hostname or ""
    if not _host_allowed(host, domains):
        return None
    if parsed.scheme == "http":
        parsed = parsed._replace(scheme="https", netloc=host)
        candidate = urlunsplit(parsed)
    if parsed.scheme != "https":
        return None
    return candidate


def _normalize_srcset(value: str, base_url: str, domains: tuple[str, ...]) -> str | None:
    normalized: list[str] = []
    for raw in value.split(","):
        parts = raw.strip().split()
        if not parts:
            continue
        url = _normalize_url(parts[0], base_url, domains)
        if url:
            normalized.append(" ".join((url, *parts[1:])))
    return ", ".join(normalized) or None


@dataclass(frozen=True)
class HtmlAdapter:
    name: HtmlAdapterName
    extraction_version: str
    root_selectors: tuple[str, ...]
    noise_selectors: tuple[str, ...]
    image_domains: tuple[str, ...]

    def prepare(self, document_html: str, *, base_url: str) -> HtmlElement:
        document = lxml_html.fromstring(document_html)
        root: HtmlElement | None = None
        for selector in self.root_selectors:
            matches = document.xpath(_selector_xpath(selector, relative=False))
            if len(matches) == 1:
                root = deepcopy(matches[0])
                break
            if len(matches) > 1:
                raise ContentAcquisitionError(
                    "unsupported_template",
                    f"adapter {self.name} found an ambiguous article container",
                    retryable=False,
                )
        if root is None:
            raise ContentAcquisitionError(
                "unsupported_template",
                f"adapter {self.name} did not find a supported article container",
                retryable=False,
            )
        for selector in (*self.noise_selectors, "script", "style", "form", "noscript"):
            for element in root.xpath(_selector_xpath(selector, relative=True)):
                element.drop_tree()
        for element in root.xpath(".//*[@hidden]"):
            element.drop_tree()
        self._normalize_media(root, base_url)
        return root

    def _normalize_media(self, root: HtmlElement, base_url: str) -> None:
        for element in root.xpath(".//img|.//source"):
            has_source = False
            for attribute in ("data-srcset", "srcset"):
                value = element.get(attribute)
                if value:
                    normalized = _normalize_srcset(str(value), base_url, self.image_domains)
                    if normalized:
                        element.set(attribute, normalized)
                        has_source = True
                    else:
                        element.attrib.pop(attribute, None)
            for attribute in ("data-src", "src"):
                value = element.get(attribute)
                if value:
                    normalized = _normalize_url(str(value), base_url, self.image_domains)
                    if normalized:
                        element.set(attribute, normalized)
                        has_source = True
                    else:
                        element.attrib.pop(attribute, None)
            if not has_source:
                element.drop_tree()


XINHUA_ADAPTER = HtmlAdapter(
    name="xinhuanet",
    extraction_version="zh-xinhua-1",
    root_selectors=("#detail", ".main-left", ".main.clearfix"),
    noise_selectors=(".editor", ".related", ".share", ".recommend", "footer"),
    image_domains=("xinhuanet.com", "news.cn"),
)

PEOPLE_ADAPTER = HtmlAdapter(
    name="people",
    extraction_version="zh-people-1",
    root_selectors=("#rm_txt_zw", ".rm_txt_con", ".layout.rm_txt"),
    noise_selectors=(
        "#rm_topnav",
        ".recommend",
        ".copyright",
        ".editor",
        ".share",
        "footer",
    ),
    image_domains=("people.com.cn", "people.cn"),
)

CHINA_NEWS_ADAPTER = HtmlAdapter(
    name="chinanews",
    extraction_version="zh-chinanews-1",
    root_selectors=("#cont_1_1_2", "#zhengwenpic", ".con_left .content"),
    noise_selectors=(
        ".recommend",
        ".hot_video",
        ".comment",
        ".editor",
        ".share",
        "footer",
    ),
    image_domains=("chinanews.com.cn", "chinanews.com", "cns.com.cn", "cnsimg.net"),
)

HTML_ADAPTER_REGISTRY: dict[HtmlAdapterName, HtmlAdapter] = {
    "xinhuanet": XINHUA_ADAPTER,
    "people": PEOPLE_ADAPTER,
    "chinanews": CHINA_NEWS_ADAPTER,
}


def get_html_adapter(name: HtmlAdapterName) -> HtmlAdapter | None:
    return HTML_ADAPTER_REGISTRY.get(name)
