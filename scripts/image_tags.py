"""Map a Gitea Git ref to published container image references."""

import re
import sys

IMAGE = "gitea.lucaswinther.info/lucasw89/recoll-modern"
RELEASE_REF = re.compile(r"refs/tags/(v[0-9]+\.[0-9]+\.[0-9]+)\Z")


def tags_for_ref(ref: str) -> list[str]:
    if ref == "refs/heads/main":
        return ["main"]
    if match := RELEASE_REF.fullmatch(ref):
        return [match.group(1), "latest"]
    return []


if __name__ == "__main__":
    for tag in tags_for_ref(sys.argv[1]):
        print(f"{IMAGE}:{tag}")
