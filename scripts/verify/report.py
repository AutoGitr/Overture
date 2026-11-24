"""The Markdown report of every check."""

lazy from .common import Case


def cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|")


def report(cases: list[Case]) -> str:
    """Render the cases as Markdown, per server, problems first."""
    problems = [case for case in cases if case.problem]
    lines = [
        "# Overture check",
        "",
        (
            f"{len(cases)} checks, {len(problems)} problems, "
            f"{sum(bool(case.note) for case in cases)} notes."
        ),
    ]
    for server in dict.fromkeys(case.server for case in cases):
        own = [case for case in cases if case.server == server]
        lines += [
            "",
            f"## {server}",
            "",
            (
                "| Library | Check | Case | Overture | Plex | Server | Members | "
                "Problem | Note |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines.extend(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    case.library,
                    case.check,
                    case.label,
                    case.count,
                    case.smart_count,
                    case.held,
                    ", ".join(case.members),
                    case.problem,
                    case.note,
                )
            )
            + " |"
            for case in sorted(own, key=lambda c: (not c.problem, not c.note))
        )
    return "\n".join(lines) + "\n"
