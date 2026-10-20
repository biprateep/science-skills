"""Grades quotations against controlled, synthetic evidence."""

import json
import pathlib
import sys


def main() -> int:
    """Checks the final JSON response for relevant verbatim evidence spans.

    Returns:
        Zero for valid evidence, one for failed output, two for bad usage.
    """
    if len(sys.argv) != 2:
        print("usage: grade.py RESPONSE_FILE")
        return 2
    sources_path = (
        pathlib.Path(__file__).parent
        / "evidence-boundaries/input/evidence.json"
    )
    sources = json.loads(sources_path.read_text(encoding="utf-8"))["sources"]
    try:
        response = json.loads(
            pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
        )
        claims = response["claims"]
        required = {
            "increase": ("A", ["12 percent", "median lifetime"]),
            "difference": ("B", ["No statistically significant difference"]),
        }
        for claim, (source, phrases) in required.items():
            quote = claims[claim]["evidence"]
            if not isinstance(quote, str) or not quote:
                print(f"{claim}: missing quotation")
                return 1
            if quote not in sources[source]["text"] or any(
                phrase not in quote for phrase in phrases
            ):
                print(f"{claim}: evidence is not a relevant verbatim span")
                return 1
        unavailable_evidence = claims["unread"]["evidence"]
        if not isinstance(unavailable_evidence, str) or unavailable_evidence:
            print("unread: evidence was invented for an unavailable text")
            return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"invalid response: {error}")
        return 1
    print("Relevant quotations match the supplied source text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
