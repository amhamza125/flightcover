# FlightCover

Parametric flight-delay cover as an Intelligent Contract on GenLayer Bradbury. You buy cover for one specific flight, and if that flight lands late, the contract pays a fixed share of your coverage — no claim form, no adjuster, no paperwork from the buyer at any point. The flight either landed late enough or it did not, and two public flight-status sources have to agree on that before a single wei moves.

Live contract (Bradbury, chain 4221): 0x958A9102175e6464f5Be9d91cC01323Bb44d17aA
Deploy transaction: 0x34e6f590eba77c712d1e972f3cef7b98aa446a11571d19b5a69ef54405791919
Source: `FlightCover.py` in this repository (sha256 786b7569d2e0b9c672bd3b11d273dc1e1b8614eabec9ca2d22dc62228c1125aa)
Proof twin (same logic, shortened clocks): 0xd3D0522Acb7DD8CF2B2c685CD87ad5EA57Bd191c, deploy transaction 0xef9b21204a75928b76556c4d242bec1276aed0ed86c8fb0477204b0bd8fe2f74

## How a policy flows

1. **Fund.** The owner seeds a GEN pool with `fund_pool`. That pool is the underwriting capital — every payout comes out of it.
2. **Buy.** Anyone buys a policy on a named flight: airline, flight number, route, flight date, and the scheduled departure and arrival instants, all committed in the policy at purchase. Coverage runs from 0.01 to 1 GEN, the premium is exactly 10% of coverage, and the full coverage amount is reserved 1:1 the moment the policy is sold, so a sold policy is always backed. One buyer can hold at most 10 open policies, and one flight can carry at most 25% of the pool's backing.
3. **Cancel.** The buyer can cancel any time up to 24 hours before departure and gets the full premium back into their payout pot. Nobody else can cancel it — a stranger's attempt is refused with `NOT_BUYER`.
4. **Assess.** From 2 hours after the scheduled arrival, and for 7 days, anyone can call `assess_policy`. The contract itself fetches the flight's page from PlaneMapper and from Avionio — the two URLs are built from the policy's own flight fields, right in the code — and an AI jury extracts the printed times from each page. Deterministic code, not the jury, then does the maths: it converts the printed times, checks that both sources describe the same flight on the same date, and requires the two sources to agree on the exact outcome before anything settles. If they disagree, if one has no arrival for that date, or if neither source's printed schedule matches the schedule committed in the policy, the assessment is recorded as a failure on the policy and no money moves. The policy stays open and can be assessed again.
5. **Settle.** The payout ladder is fixed: arrival delay under 60 minutes pays nothing (`NONE`), 60 to 179 minutes pays 25% of coverage (`PARTIAL`), and 180 minutes or more, a cancellation, or a diversion pays 100% (`FULL`). The payout is credited to the buyer's pot, the reservation is released, and the rest of the reserved coverage returns to the pool.
6. **Lapse.** A policy that nobody assesses inside its 7-day window can be closed by anyone with `finalize_lapsed`. Its reservation returns to the pool and the premium stays with the pool.
7. **Withdraw.** Pots pay out pull-style, the same pattern used across this contract family: `claim_payout` starts the transfer and records it as the one pending payout for that payee, `confirm_withdrawal` completes it once the GEN has landed. While a payout stands pending, a second claim is refused with `PENDING_EXISTS`, so a pending amount can never be emitted twice. A pending can be returned to the pot by `restore_pending` only once it is at least 24 hours old and the contract physically holds enough GEN to back everything it owes — a transfer still on its way can never be restored and paid again. If a transfer landed but was never confirmed, `write_off_pending` clears it after 7 days, and only against a real shortfall: on a fully backed contract it is refused with `NO_SHORTFALL`.
8. **Pool and admin.** The owner can withdraw free pool funds with `withdraw_pool` (never the reserved coverage), pause new sales with `set_paused`, and hand ownership over in two steps with `transfer_ownership` and `accept_ownership`. Cancels, assessments, claims and restores all keep working while sales are paused.

## Why two sources, and why the schedule check matters

One status site can be wrong, slow, or show a different flight's row. FlightCover therefore settles only when PlaneMapper and Avionio independently produce the same outcome tuple for the same flight and date. The jury also has to show its working on the schedule: at least one source must print a scheduled arrival that matches the arrival time committed when the policy was bought, computed from a timezone the source itself printed. A schedule derived from the committed time cannot vouch for that same time, so derived schedules never count as corroboration. A policy sold against a made-up schedule — for example, an arrival time shifted four hours early — is caught by that check and recorded as `SCHEDULE_MISMATCH`, with the policy left open and unpaid.

## Reading the contract

All state is public and readable without a wallet. Views (4): `get_policy`, `get_overview`, `get_claimable`, `get_pending`. The overview reports the policy count, the free pool (`poolf`), reserved coverage (`resw`), claimable pots (`tcw`) and payouts in transit (`tpw`), next to the raw contract balance, so anyone can check that the balance covers everything the contract owes.

Write methods (13): `fund_pool`, `buy_policy`, `cancel_policy`, `assess_policy`, `finalize_lapsed`, `claim_payout`, `confirm_withdrawal`, `restore_pending`, `write_off_pending`, `withdraw_pool`, `set_paused`, `transfer_ownership`, `accept_ownership`.

Every rejected call raises a named error (for example `BAD_PREMIUM`, `POOL_INSUFFICIENT`, `WINDOW_CLOSED`, `PENDING_EXISTS`, `PENDING_TOO_YOUNG`, `NO_SHORTFALL`) and changes no state and moves no funds.

## Verification

- The contract source in this repo is byte-identical to the deployed production source (SHA-256 above).
- Offline test suite (`tests/test_pure.py`, stubbed GenVM): **46/46 passing** — every gate and error code, the two-source agreement and schedule-corroboration rules, all three settlement branches, the lapse and cancel paths, and the payout pattern's age, backing and shortfall rules, with fund conservation asserted after every scenario. Run it with `python3 test_pure.py` inside `tests/`.
- Live proof ran on the twin above (same logic; assessment opens after 120 seconds instead of 2 hours, and the restore and write-off delays are 300 and 1,200 seconds, so the full lifecycle fits in one session): a real delayed flight settled `PARTIAL` and paid exactly 0.025 GEN; a policy sold against a shifted schedule was recorded `SCHEDULE_MISMATCH` and paid nothing; a second claim while a payout stood pending was refused with `PENDING_EXISTS`, an early restore with `PENDING_TOO_YOUNG`, and a write-off on a fully backed pending with `NO_SHORTFALL`. Fund conservation held at all 11 checkpoints. Full record in `PROOF.md`.
- Production is live and funded with 0.5 GEN: policy 1 (EK215, Dubai to Los Angeles, 2026-11-23) is open as the standing exhibit, and policy 2 was bought, cancelled, and its premium refund claimed and confirmed.

One plain limitation, stated up front: if no flight in the assessment window has both sources printing the same large delay or cancellation, the `FULL` branch cannot be exercised live on real flights — it is covered by the offline suite (tests 20 and 23) and the live record says so openly rather than dressing up a different flight as a substitute.
