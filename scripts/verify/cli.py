"""The verify command: what it checks, and its report."""

lazy import argparse
lazy import asyncio
lazy import json
lazy import sys
lazy from pathlib import Path
lazy from typing import Any

lazy from scripts.verify import __doc__ as verify_doc

lazy from .checks import servers, verify_overture
lazy from .common import Case, api_key
lazy from .report import report
lazy from .services import check_services
lazy from .writes import WriteCheck, compare_writes


async def run(args: argparse.Namespace) -> int:
    extra: list[dict[str, Any]] = (
        json.loads(args.sources.read_text()) if args.sources else []
    )
    cases: list[Case] = []
    verify = not args.insecure
    given = servers(args, verify)
    direct = {server.server: server for server, _, _ in given}
    try:
        cases.extend(
            await verify_overture(args.url, api_key(), extra, direct, verify=verify)
        )
        cases.extend(await check_services(args, verify))
        if args.write:
            checks: list[WriteCheck] = []
            for server, url, secret in given:
                print(f"Writing to {server.server}...", flush=True)
                check = WriteCheck(server, url, secret, verify=verify)
                cases.extend(await check.run())
                checks.append(check)
            cases.append(compare_writes(checks))
    finally:
        for server in direct.values():
            await server.client.aclose()
    text = report(cases)
    if args.report:
        args.report.write_text(text)
        print(f"Wrote {args.report}")
    else:
        print(text)
    return 1 if any(case.problem for case in cases) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=verify_doc)
    parser.add_argument("url", help="Overture's address, such as http://localhost:5885")
    parser.add_argument("--report", type=Path, help="Write the Markdown report here")
    parser.add_argument(
        "--sources", type=Path, help="A JSON list of extra source objects to test"
    )
    parser.add_argument("--plex", help="Plex's address; PLEX_TOKEN holds its token")
    parser.add_argument(
        "--jellyfin", help="Jellyfin's address; JELLYFIN_API_KEY holds its key"
    )
    parser.add_argument("--emby", help="Emby's address; EMBY_API_KEY holds its key")
    parser.add_argument(
        "--radarr", help="Radarr's address; RADARR_API_KEY holds its key"
    )
    parser.add_argument(
        "--sonarr", help="Sonarr's address; SONARR_API_KEY holds its key"
    )
    parser.add_argument(
        "--insecure", action="store_true", help="Skip TLS certificate verification"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            'Also make, change and delete temporary "zz Overture verify" '
            "collections on each media server given"
        ),
    )
    sys.exit(asyncio.run(run(parser.parse_args())))
