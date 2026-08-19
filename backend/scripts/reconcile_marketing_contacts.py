from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Optional

from supabase import create_client

from backend.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from backend.services.resend_marketing import set_contact_unsubscribed


@dataclass
class ReconciliationItem:
    user_id: str
    email: Optional[str]
    marketing_opt_in: Optional[bool]
    desired_unsubscribed: Optional[bool]
    status: str  # "planned" or "skipped_missing_user_or_email"


@dataclass
class ReconciliationSummary:
    items: list[ReconciliationItem] = field(default_factory=list)
    synced: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


def fetch_preference_rows(supabase) -> list[dict]:
    result = (
        supabase.table("marketing_email_preferences")
        .select("user_id,marketing_opt_in")
        .execute()
    )
    return result.data or []


def fetch_user_emails(supabase, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}

    result = (
        supabase.table("topspot_users")
        .select("id,email")
        .in_("id", user_ids)
        .execute()
    )

    emails: dict[str, str] = {}

    for row in result.data or []:
        raw_email = row.get("email")
        if raw_email:
            emails[str(row["id"])] = raw_email.strip().lower()

    return emails


def build_plan(
    preferences: list[dict],
    emails: dict[str, str],
) -> list[ReconciliationItem]:
    plan: list[ReconciliationItem] = []

    for row in preferences:
        user_id = str(row.get("user_id"))
        marketing_opt_in = bool(row.get("marketing_opt_in"))
        email = emails.get(user_id)

        if not email:
            plan.append(
                ReconciliationItem(
                    user_id=user_id,
                    email=None,
                    marketing_opt_in=marketing_opt_in,
                    desired_unsubscribed=None,
                    status="skipped_missing_user_or_email",
                )
            )
            continue

        plan.append(
            ReconciliationItem(
                user_id=user_id,
                email=email,
                marketing_opt_in=marketing_opt_in,
                desired_unsubscribed=not marketing_opt_in,
                status="planned",
            )
        )

    return plan


def reconcile(supabase, apply: bool) -> ReconciliationSummary:
    preferences = fetch_preference_rows(supabase)
    user_ids = [str(row["user_id"]) for row in preferences if row.get("user_id")]
    emails = fetch_user_emails(supabase, user_ids)

    plan = build_plan(preferences, emails)
    summary = ReconciliationSummary(items=plan)

    for item in plan:
        if item.status != "planned":
            summary.skipped += 1
            print(
                f"SKIP  user_id={item.user_id} "
                f"marketing_opt_in={item.marketing_opt_in} "
                "reason=missing_topspot_user_or_email"
            )
            continue

        if not apply:
            print(
                f"WOULD_SYNC user_id={item.user_id} email={item.email} "
                f"marketing_opt_in={item.marketing_opt_in} "
                f"desired_unsubscribed={item.desired_unsubscribed}"
            )
            continue

        try:
            set_contact_unsubscribed(item.email, item.desired_unsubscribed)
        except Exception as exc:
            summary.failed += 1
            print(
                f"FAILED user_id={item.user_id} email={item.email} "
                f"desired_unsubscribed={item.desired_unsubscribed} error={exc}"
            )
            continue

        summary.synced += 1
        print(
            f"SYNCED user_id={item.user_id} email={item.email} "
            f"desired_unsubscribed={item.desired_unsubscribed}"
        )

    return summary


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile TopSpot40's canonical marketing_email_preferences "
            "state to Resend. Dry-run by default; pass --apply to write."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually call Resend to sync contacts. "
            "Without this flag, only reports what would change."
        ),
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    print("=" * 80)
    print("Reconcile Marketing Contacts (Supabase -> Resend)")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 80)

    summary = reconcile(supabase, apply=args.apply)

    print("=" * 80)
    print(f"Planned:  {len(summary.items)}")
    print(f"Skipped:  {summary.skipped}")
    print(f"Synced:   {summary.synced}")
    print(f"Failed:   {summary.failed}")
    print("=" * 80)

    sys.exit(summary.exit_code)


if __name__ == "__main__":
    main()
