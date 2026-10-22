"""Vendor or check the authoritative OvertureDB catalog contract."""

lazy import argparse
lazy from pathlib import Path

DESTINATION = (
    Path(__file__).resolve().parents[1] / "src/overture/services/public_dataset/schema"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="OvertureDB checkout")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    # The contract is every module and schema OvertureDB keeps in schema/.
    names = sorted(
        path.name
        for path in (args.source / "schema").iterdir()
        if path.suffix in {".py", ".json"} and path.name != "__init__.py"
    )
    for name in names:
        source = (args.source / "schema" / name).read_text()
        target = DESTINATION / name
        if args.check:
            if not target.exists() or target.read_text() != source:
                print(
                    f"Overture's copy of the OvertureDB contract differs: {name}. "
                    "Update it with: uv run python -m scripts.dataset_contract "
                    "<OvertureDB checkout> (run in Overture)"
                )
                return 1
        else:
            DESTINATION.mkdir(parents=True, exist_ok=True)
            target.write_text(source, newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
