"""Grades controlled citation evidence against the private fixture rubric."""

import pathlib
import sys

import score


def main() -> int:
    """Checks relevant verbatim spans and unavailable-evidence restraint.

    Returns:
        Zero for valid evidence, one for failed output, two for invalid usage.
    """
    if len(sys.argv) not in (2, 3):
        print("usage: grade.py RESPONSE_FILE [CASE_ID]")
        return 2
    case_id = sys.argv[2] if len(sys.argv) == 3 else "evidence-boundaries"
    repo = pathlib.Path(__file__).resolve().parents[3]
    _, suite = score.load_suite(repo)
    if case_id not in suite:
        print(f"Unknown citation case: {case_id}")
        return 2
    try:
        response = score.read_output(pathlib.Path(sys.argv[1]), 1024 * 1024)
        claims = response.get("claims")
        if not isinstance(claims, dict):
            raise ValueError("claims must be an object")
        for claim_id, gold in suite[case_id].items():
            _, anchored, restraint = score.evidence_checks(
                claims.get(claim_id), gold
            )
            if not (restraint if gold.source_text is None else anchored):
                print(f"{claim_id}: missing, invented, or irrelevant evidence")
                return 1
    except (OSError, ValueError, RecursionError) as error:
        print(f"Invalid response: {error}")
        return 1
    print("Relevant verbatim spans and inaccessible-evidence restraint passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
