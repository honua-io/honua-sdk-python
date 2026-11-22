"""Check that the documentation sitemap covers the rendered pages."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    parser.add_argument("base_url")
    args = parser.parse_args()

    pages = args.site.rglob("index.html")
    expected = {
        urljoin(args.base_url.rstrip("/") + "/", page.relative_to(args.site).as_posix().removesuffix("index.html"))
        for page in pages
    }
    # The input is generated locally by the documentation build.
    sitemap = ElementTree.parse(args.site / "sitemap.xml")  # noqa: S314
    urls = [node.text or "" for node in sitemap.findall("{*}url/{*}loc")]
    actual = set(urls)
    if not actual or actual != expected or len(urls) != len(actual):
        parser.exit(
            1,
            f"Invalid sitemap: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}, entries={len(urls)}\n",
        )
    print(f"Sitemap covers all {len(actual)} rendered documentation pages.")


if __name__ == "__main__":
    main()
