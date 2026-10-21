# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
# ---
# %%
"""Opt-in public registry probes, separate from regression tests."""

import argparse
import http.client
import json
import re
import sys
import typing
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

MAX_BYTES = 1024 * 1024
TIMEOUT = 15
PROBES = {
    "crossref": "https://api.crossref.org/works/10.1103%2FPhysRev.47.777",
    "datacite": "https://api.datacite.org/dois/10.5281/zenodo.3509134",
    "arxiv": "https://export.arxiv.org/api/query?id_list=1706.03762&max_results=1",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so probes stay within their explicit public URLs."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: typing.Any,
        code: int,
        msg: str,
        headers: typing.Any,
        newurl: str,
    ) -> None:
        """Leave redirects as classified HTTP errors without following them."""
        del req, fp, code, msg, headers, newurl
        return None


def _matches(name: str, body: bytes) -> bool:
    if name == "arxiv":
        document = ET.fromstring(body)
        ids = [
            entry.text or ""
            for entry in document.findall(
                "{http://www.w3.org/2005/Atom}entry/{http://www.w3.org/2005/Atom}id"
            )
        ]
        return (
            len(ids) == 1
            and re.search(r"/1706\.03762(?:v[1-9]\d*)?$", ids[0]) is not None
        )
    data = json.loads(body.decode("utf-8"))
    if name == "crossref":
        value = data.get("message", {}).get("DOI")
        return (
            isinstance(value, str) and value.lower() == "10.1103/physrev.47.777"
        )
    value = data.get("data", {}).get("attributes", {}).get("doi")
    return isinstance(value, str) and value.lower() == "10.5281/zenodo.3509134"


def probe(name: str, url: str) -> dict[str, typing.Any]:
    """Make one bounded request to an allowlisted public fixture."""
    if name not in PROBES or PROBES[name] != url:
        raise ValueError("probe URL is not allowlisted")
    result: dict[str, typing.Any] = {
        "provider": name,
        "source": url,
        "status": None,
        "outcome": "unavailable",
        "detail": "request not completed",
    }
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "science-skills-public-availability-probe/1",
            "Accept": "application/atom+xml"
            if name == "arxiv"
            else "application/json",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=TIMEOUT
        ) as response:
            result["status"] = response.status
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                result.update(
                    outcome="contract-failure", detail="response exceeded 1 MiB"
                )
            elif response.status != 200:
                result.update(
                    outcome="contract-failure", detail="unexpected HTTP status"
                )
            elif _matches(name, body):
                result.update(
                    outcome="available",
                    detail="public fixture identity matched",
                )
            else:
                result.update(
                    outcome="contract-failure",
                    detail="public fixture identity did not match",
                )
    except urllib.error.HTTPError as error:
        result.update(
            status=error.code,
            outcome=(
                "unavailable"
                if error.code in (401, 403, 408, 429) or error.code >= 500
                else "contract-failure"
            ),
            detail="public provider returned an HTTP error",
        )
        error.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        result.update(
            outcome="unavailable",
            detail="public provider connection failed or timed out",
        )
    except (
        ValueError,
        UnicodeError,
        AttributeError,
        TypeError,
        ET.ParseError,
        http.client.HTTPException,
    ):
        result.update(
            outcome="contract-failure",
            detail="public provider response was malformed",
        )
    return result


def run_probes() -> dict[str, typing.Any]:
    """Report providers independently; this is not a regression test."""
    results = [probe(name, url) for name, url in PROBES.items()]
    return {
        "kind": "provider-availability",
        "results": results,
        "ok": all(result["outcome"] == "available" for result in results),
    }


def main(argv: list[str] | None = None) -> int:
    """Require live opt-in and return nonzero for provider issues."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args(argv)
    report = run_probes()
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0 if report["ok"] else 1


# %%
if __name__ == "__main__":
    raise SystemExit(main())
