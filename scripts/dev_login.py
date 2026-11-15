# ruff: noqa: ASYNC250  (interactive CLI: blocking input() is intended)
"""Developer tool: sign in to Skolengo with the integration's API client, from a terminal.

Searches the school, lists the identity providers, asks for the EduConnect login and password
(the password is typed hidden, never stored nor printed), signs in without a browser and checks the
account. With ``--save PATH`` the tokens are written to PATH (chmod 600) for local testing.

Usage (from the repository root):
    .venv/bin/python scripts/dev_login.py "college name or town" [--provider ID] [--save PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "skolengo"))

from api import (  # noqa: E402
    SkolengoClient,
    SkolengoError,
    async_get_identity_providers,
    async_login,
    async_search_schools,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("school", help="school name or town")
    parser.add_argument("--provider", help="identity provider id (asked when omitted)")
    parser.add_argument("--save", type=Path, help="write the tokens to this file (chmod 600)")
    args = parser.parse_args()

    async with aiohttp.ClientSession() as session:
        schools = await async_search_schools(session, args.school)
        if not schools:
            print("No school found.")
            return 1
        for i, school in enumerate(schools):
            print(f"  [{i}] {school.name} — {school.city} ({school.ems_code})")
        school = schools[int(input("School number: ") or 0)] if len(schools) > 1 else schools[0]

        provider = args.provider
        if provider is None:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as probe:
                providers = await async_get_identity_providers(probe, school)
            for i, p in enumerate(providers):
                print(f"  [{i}] {p.category or ''} {p.label}  ({p.id})")
            if providers:
                provider = providers[int(input("Identity provider number: "))].id

        username = input("Login: ").strip()
        password = getpass.getpass("Password (hidden): ")

        # The sign-in needs its own cookie jar, closed right after.
        async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as login_session:
            try:
                tokens = await async_login(login_session, school, username, password, provider)
            except SkolengoError as err:
                print(f"Sign-in failed: {type(err).__name__}: {err}")
                return 1
        del password
        print("Signed in without a browser.")

        account = await SkolengoClient(session, tokens, school.ems_code).async_get_account()
        names = ", ".join(s.first_name for s in account.students) or "-"
        print(f"Account type: {account.type}; students: {names}")

        if args.save:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            args.save.write_text(json.dumps({**tokens.as_dict(), "ems_code": school.ems_code}, indent=2))
            os.chmod(args.save, 0o600)
            print(f"Tokens written to {args.save} (600).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
