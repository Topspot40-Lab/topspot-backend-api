# TopSpot40 Access Codes

Signed-in members can apply an access code from the membership page or Manage Account / Subscription. Codes grant complimentary access without creating a Stripe subscription. Deploy the database migration, then the backend, then the frontend. No example or production codes are created by the migration.

## Manage codes

In Supabase Table Editor, select `public.access_codes`. This table is administrator-only; the browser cannot list or edit codes.

| Column | Setting |
| --- | --- |
| `code` | Unique lowercase word/code, 3–64 letters, numbers, hyphens, or underscores. |
| `active` | TRUE accepts new redemptions; FALSE stops them. |
| `description` | Optional internal note about the group or offer. |
| `redeem_by` | Optional UTC deadline for new redemptions. |
| `access_expires_at` | Optional fixed UTC access end. |
| `access_days` | Optional whole days from first redemption, 1–36500. |

Leave both access expiration fields blank for no expiration. Otherwise fill **one** of `access_expires_at` or `access_days`. `redeem_by` is independent: closing redemption does not expire access already granted.

Fixed deadlines are exclusive timestamps. To grant access through December 31 in America/Chicago, choose midnight January 1 in that timezone, converted to UTC. The form displays the end date using the member's device timezone and selected interface language.

Used codes can be deactivated and their terms edited for **future** recipients. Existing grants are snapshots and do not change. Used codes cannot be renamed or deleted. Unused codes can be deleted. Create a new code to run a fresh offer rather than restarting an existing code.

## Records

`access_code_redemptions` records one row per user and code: normalized code, redemption timestamp, offered expiration, and whether this offer changed access. Filter by `access_code_id` to see recipients. `topspot_users` stores the code and timestamp responsible for the current complimentary grant in `complimentary_access_code` and `complimentary_access_granted_at`.

The grant uses the existing `complimentary_access` boolean and `complimentary_access_expires_at` timestamp. NULL expiration means no expiration. Reapplying a code never restarts its duration, even after it expires. A different code may extend an existing grant, but can never shorten it. An offer that does not improve access is recorded once with `access_changed = false`.

A code may be shared with multiple accounts. Deactivation does not revoke their memberships. Redemption accepts case variations and surrounding spaces. Each account can submit 10 correctly formatted attempts in a 15-minute window; counters live in the database, so restarts and multiple backend workers do not bypass the limit.

Paid accounts (`active` or `past_due` Stripe subscriptions) receive an explanatory message instead of a new grant. Access codes do not cancel billing. Arrange any transition from paid membership separately; this feature never modifies Stripe subscriptions, invoices, or payment methods.

## API and security

`POST /api/access-codes/redeem` accepts JSON `{ "code": "..." }`, the existing HTTP-only `access_token` session cookie, and `X-TopSpot-Access-Code: 1`. The authenticated user ID comes only from the verified backend session. The request model rejects additional fields such as another user's ID or a requested expiration.

The backend calls the service-role-only `redeem_access_code` database function. A transaction locks the user and code, validates the offer, checks existing access, writes the audit row, and grants access together. All three new tables have RLS and no grants to `anon` or `authenticated`. The function uses SECURITY INVOKER and cannot be invoked by browser roles. Submitted codes and session tokens are not logged or sent as application analytics events.

## Validation

- `python -m pytest backend/tests/test_access_codes.py backend/tests/test_offer_access.py -q`
- Run `backend/tests/access_codes_database.sql` after the migration inside a transaction and finish with `ROLLBACK`. It uses synthetic users and checks expiration, repeat redemption, longer access, inactive codes, deletion protection, paid billing protection, attempt limits, and role permissions.
- Frontend: `node --import tsx --test tests/accessCodes.test.mjs tests/membershipBilling.test.js tests/authProfileMenu.test.js` and `npm run check`.
- Acceptance: sign in locally, create a temporary code in Table Editor, apply it, verify the confirmation, continue to the dashboard, reopen Manage Account, and verify the stored access state. Also test one invalid code, one disabled code, and a dated offer. Deactivate the temporary code afterward.

Changes are registered through the existing billing router; `backend/main.py` does not need to change. Preserve any uncommitted local changes when bringing in the branch.
