"""Work-log snapshot comparison (feature to implement)."""


def compare_records(before, after):
    raise NotImplementedError


def render_diff(changes, *, format="json"):
    raise NotImplementedError


def main(argv=None, *, stdin=None, stdout=None, stderr=None):
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
