# FlightCover — live proof record

Everything below was executed on chain and can be checked on the Bradbury explorer (https://scan.bradbury.genlayer.com). Amounts are wei unless a GEN figure is named (1 GEN = 1,000,000,000,000,000,000 wei).

## Deployments

| Deployment | Address | Deploy tx |
|---|---|---|
| Production | `0x958A9102175e6464f5Be9d91cC01323Bb44d17aA` | `0x34e6f590eba77c712d1e972f3cef7b98aa446a11571d19b5a69ef54405791919` |
| Proof twin (shortened clocks) | `0xd3D0522Acb7DD8CF2B2c685CD87ad5EA57Bd191c` | `0xef9b21204a75928b76556c4d242bec1276aed0ed86c8fb0477204b0bd8fe2f74` |

Both deploys finalized with MAJORITY_AGREE / FINISHED_WITH_RETURN and were read back through the contract's own views. The production source is `FlightCover.py` in this repo, sha256 `786b7569d2e0b9c672bd3b11d273dc1e1b8614eabec9ca2d22dc62228c1125aa` (30,332 bytes). The twin runs the same logic with shortened time constants — assessment opens 120 seconds after scheduled arrival instead of 2 hours, the restore delay is 300 seconds instead of 24 hours, and the write-off delay is 1,200 seconds instead of 7 days — and with the buy-side lead and horizon gates relaxed, so policies on flights that have already landed can be bought and assessed in one session. The twin source sha256 is `ac767529eb596132783445d302d890a204414cd80759885388175288fba38756`.

The live run used three test wallets: A `0xD2aF69BB67d446526661A80a280820599c601ed3` (owner), B `0x0BbA411375d7074178980E610B5311dD6Ed34d74` (buyer), C `0x6FA23bD191266A8680C195eC6a618d2d9d584CaB` (outsider).

## Offline suite

`tests/test_pure.py` (stubbed GenVM, run locally): **46 passed, 0 failed** — every gate and error code, the two-source agreement rules, the schedule-corroboration rules including the cases where a schedule derived from the committed time must not corroborate it, all three settlement branches (tests 20 and 23 cover `FULL`), the lapse and cancel paths, and the payout pattern's single-pending, age, backing and shortfall rules. Fund conservation is asserted after every scenario. The same suite run against the copy in this repository also passes 46/46.

## Live proof — proof twin

The twin was funded with 1 GEN (tx `0xfddb4a7d1b7bd2c9d750f13cad5d360daec9f75f5e5f07720e948407d52009c8`) and five policies were bought by B, each with 0.1 GEN coverage at a 0.01 GEN premium: policy 1 KL605 Amsterdam–San Francisco 2026-11-13, policy 2 EK215 Dubai–Los Angeles 2026-11-19, policy 3 EK215 2026-11-23 (the cancel case), policy 4 EK215 2026-11-11 (the lapse case), and policy 5 EK215 2026-11-19 with its scheduled arrival committed four hours early (the fake-schedule case). Fund conservation was read at 11 checkpoints across the whole run and held at every one.

### Outsider attacks and buy gates

- A stranger (C) cancelling B's policy was refused with `NOT_BUYER` — tx `0x0aa9bd3abb8b8e83d4890a50a9a52729e473f4a4615523f16d927e2f0653253e`.
- A stranger calling `withdraw_pool` was refused with `NOT_ADMIN` — tx `0xd08a76e01eee1d626d253ebdc9449f256cc8c670e2956e82a7962fffa56a7cea`.
- A buy with the wrong premium was refused with `BAD_PREMIUM` — tx `0xbafc1e820c8d738a4a95e42d51a50f971354a101db96d80c0191b43f13a7e565`.
- A buy the pool could not back was refused with `POOL_INSUFFICIENT` — tx `0x4a4383ae370aa1c02ff86f26e84cb7534438f01002c381f3053496d3d3de6e09`.

Each refusal finalized with FINISHED_WITH_ERROR / MAJORITY_AGREE, changed no state and moved no funds. The rejected premiums stay visible in the contract's physical balance as unaccounted strays — 0.114 GEN in total across the run — which is why the twin's physical balance sits above its accounted total (see the emission note below).

### Lapse

Policy 4's assessment window had already closed when it was bought on the twin. Assessing it was refused with `WINDOW_CLOSED` (tx `0x70a7514ed543a0d929ea154baa75c5612c0348c1105694b98af05519657d763d`), `finalize_lapsed` then closed it (tx `0x7b6bccd9d583519e403ddd9e449896abf12e1a1ec8d763f6ed4d7a2ea8412096`, state `LAPSED`, reservation returned to the pool), and a further assessment was refused with `BAD_STATE` (tx `0x37bf38f87f24ad6f54d3cd36d78daf751f8f74686dc2040fe6d3f11260df7eed`).

### PARTIAL settlement — paid exactly 0.025 GEN

Policy 1, KL605 on 2026-11-13: PlaneMapper printed an estimated arrival 77 minutes after the scheduled arrival and Avionio printed a landing 86 minutes late — both sources in the 60–179 minute band, agreeing on the exact tuple. Assessment tx `0xa11bffefda08f173ad51c72938c4c26e5e1bb6ae4063c55e730fbcc5cf490c57` settled on attempt 1 with MAJORITY_AGREE: verdict `PARTIAL`, basis `DELAY`, reason `ARRIVAL_DELAY_60_TO_179`, state `PAID_PARTIAL`, payout exactly 25,000,000,000,000,000 wei (0.025 GEN, 25% of the 0.1 GEN coverage), credited to B's pot and read back from the contract.

### Fake schedule — recorded SCHEDULE_MISMATCH, paid nothing

Policy 5 covers the same EK215 flight on the same date as policy 2, but its scheduled arrival was committed four hours earlier than the true schedule. Both status pages were re-probed live during the run and returned HTTP 200 with the flight's rows present. On the fourth assessment attempt (tx `0xa49f21801a137c96f3ee11d65be82463b689f37bb0e525591a869b7d78dd25d6`) the policy recorded exactly `SCHEDULE_MISMATCH` as its last failure: neither source's printed schedule corroborates the shifted time, and a schedule derived from the committed time does not count. The policy stayed `OPEN`, its payout stayed 0, and B's claimable balance did not change. The three earlier attempts recorded `EVIDENCE_UNAVAILABLE` — the jury's page extraction varies between attempts, which is exactly why a failed assessment records a failure and leaves the policy open instead of settling on partial evidence.

### The payout pattern, attacked live

B's pot after the PARTIAL payout and a cancel refund held 0.035 GEN. The claim and gate sequence ran as follows:

- **PENDING_EXISTS.** B claimed the pot (tx `0x79aee1be533c22c2d9c2d1b8a4b6e2bdd8ef487282365ea778b41c008f1bfc36`), a second policy's refund was credited on top, and B's second `claim_payout` was refused with `PENDING_EXISTS` — tx `0x730714c32ab41420ef07a062c965b90c1d0f9d9124c873360a1ef9cdb0a7e4be`. The pending record stood byte-identical before and after the refused claim, and no funds moved.
- **PENDING_TOO_YOUNG.** With a fresh 0.035 GEN pending standing (claim tx `0xf91028624ff3eaff776d77c78c165af9b6a993c2d80b812f921b7c2c1dd949d6`) and a stray top-up already sitting in the contract balance, an immediate `restore_pending` was refused with `PENDING_TOO_YOUNG` — tx `0x73d36474dd1dc562c4c651115546c9dcd55d32790167e78d5123d2a61b232d01`. A stray balance does not buy out the age gate.
- **NO_SHORTFALL.** The same pending, aged 1,231 seconds (past the twin's 1,200-second write-off delay) and fully backed, was put to `write_off_pending` by the owner and refused with `NO_SHORTFALL` — tx `0xe5f8857b38c69262a16a806b9273566561094e44f80a9d75bdc916de670ff176`. A pending on a fully backed contract cannot be extinguished.

## NONE branch — EK215, 2026-11-19

Policy 2 covers EK215 on 2026-11-19, a flight that landed early on both sources: PlaneMapper printed an estimated arrival of 13:14 PST against a 13:50 scheduled arrival (−36 minutes) and Avionio printed a landing at 13:17 (−33 minutes), so the expected verdict is `NONE` with no payout. This branch has **not settled live yet**, and this record does not claim it has.

In the original run the policy was assessed five times. Four attempts recorded `EVIDENCE_UNAVAILABLE` on the policy (txs `0x4a27077a973543f41992169583aeb83ecc509eedf91613b4c9a689a676daed36`, `0x7eea54fdee919773824392e920a52cd585a603e4214ed33f7e055236fb23c12d`, `0xd0c2947a1db696817af8bc27c99e993f3110b4051b96f2fae8cac1352df0351a`, `0xeb09a571094e383c47c177ce2fab3e7b341906d3ce6b35a61ce1793bfb0eff1b`; the failure counter reached 4) and one attempt ended with NO_MAJORITY and recorded nothing (tx `0x304c31dc74290c3b9e3bbdd24d40fbab408101d566712138b4400813ae473b5e`). Both source pages were re-probed during the same run and returned HTTP 200 with the flight's rows present, so the failures are jury extraction variance, not missing evidence and not a contract fault — the same flight's fake-schedule policy did record its `SCHEDULE_MISMATCH` verdict in the same session.

On 2026-11-21 the policy was retried three more times from the buyer (txs `0x5aa1df744878443338b3212f75536e415d3c4934a42b2b46b916b02ceb3e10de`, `0x8aa3be475ee964c68a7534be759c3749cc3de1e0f6f7a95a970726f7e5872086`, `0xde9bd6c3d06e284ecc5fbbcc7d69f98aa3c74bd9eec278db7f03cce2eaec6f28`). All three transactions appear on the explorer as finalized, but each one's round record shows the result `idle` with an empty validator list and zero votes — the validator round never ran, so nothing executed and nothing was recorded. The policy was read back after every attempt, unchanged: still `OPEN`, failure count still 4, last failure still `EVIDENCE_UNAVAILABLE`, payout 0.

The policy remains open and assessable until 2026-11-26T21:50Z, and a later retry inside that window is legitimate — the verdict depends on validator and jury variance, not on any state that has been used up. Until it settles, the `NONE` settlement branch stands on the offline suite: test 22 settles an agreed under-60-minute arrival as `NO_PAYOUT` with the premium moving to the pool, and tests 17 and 25 cover the record-a-failure-then-settle-on-retry shape.

## FULL branch — the honest gap

No live `FULL` settlement is claimed, because no real flight in the assessment window qualified. A widened scan of roughly 80 flights across both sources for 13–19 November 2026 found no flight-date where both sources print a landed arrival with both delays at or above 180 minutes, and no both-sources cancellation: PlaneMapper prints no cancellation tuple, so a pure cancellation can never get the second source's agreement and fails closed by design. The closest candidates split between the sources (for example BA179 on 2026-11-19: PlaneMapper +137 minutes against Avionio −29 minutes). The branch is covered by the offline suite — test 20 (delay at or above 180 minutes pays 100%) and test 23 (an agreed cancellation pays 100%) — and the gap is recorded here rather than filled with a substitute flight dressed up as a FULL case.

## Production staging

Production was funded with 0.5 GEN (tx `0x4f9a272ba82d415a00b92ff539b6ad32a2db40db7e6a721eb4f1c3ceb55a58f9`). Policy 1 — EK215 Dubai–Los Angeles, 2026-11-23, 0.1 GEN coverage — was bought by B (tx `0x89201d35481b148e959294cda0cf28b0945edf98ae2576daa4d4a12be5a8e59b`) and stands `OPEN` as the exhibit policy. Policy 2, the same flight on the same date, was bought (tx `0xf4b13b212cac09a985ec212d8f691ebf7518e7dc88002e2458f0af75f8fd451d`) and cancelled by its buyer before the cutoff (tx `0x202e18574eac783a502d67ff0fe35363749ee33311b76508a8dc7e37d9d1408b`, state `CANCELLED`); its premium refund was claimed (tx `0xd29ab43c654315899e81f03eddfa3485df58adeaac110cd0300983ea83362628`) and the withdrawal confirmed (tx `0x503359e83893ab95a35fbab8dcf80b5081d3b12c0d10395277050f2a270682da`). Final production counters: free pool 0.41 GEN, reserved 0.1 GEN, claimable 0, in transit 0, 2 policies.

## Two emissions still in Bradbury's execution queue

Two claim transfers were emitted by finalized, MAJORITY_AGREE transactions and are still waiting in Bradbury's execution queue — a delay on the chain's side, not in the contract's accounting, where every wei is accounted for:

- On the twin, the 0.035 GEN claim (tx `0xf91028624ff3eaff776d77c78c165af9b6a993c2d80b812f921b7c2c1dd949d6`) stands recorded as in transit (`tpw` 0.035 GEN). The twin's physical balance exceeds its accounted total by exactly 0.114 GEN — the stray total from the refused buys across the run, which includes that in-flight 0.035 GEN.
- On production, the 0.01 GEN premium refund (claim tx `0xd29ab43c654315899e81f03eddfa3485df58adeaac110cd0300983ea83362628`, confirmed in tx `0x503359e83893ab95a35fbab8dcf80b5081d3b12c0d10395277050f2a270682da`) is still in flight: the physical balance exceeds the accounted total by exactly 0.01 GEN.

A watcher process follows both contracts and, the moment each transfer lands, completes the remaining payout checks on the twin (an aged restore against the landed pending must be refused with `INSUFFICIENT_BACKING`, then the withdrawal is confirmed and the recipient's balance step is measured) and the final production counters. Until the chain executes the transfers, the funds sit fully accounted inside the contracts, owed to exactly one payee each.
