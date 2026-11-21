"""FlightCover v1.1 offline suite — spec §12 tests 1-42 as amended by
SPEC-v1.1-delta §6 (39 carried over, 12/15/18 rewritten in slot, new
43 template construction, 44 header + anchoring, 45 mixed non-tuple
guards, 46 independent corroboration (Amendment A1); 46 tests total)
+ §9 worked example.

Run:  python3 test_pure.py            (production v1.1 source)
      FC_SRC=../FlightCover.v1.1.twin.py python3 test_pure.py   (twin
      smoke: only the tests marked twin-safe run green there; the full
      suite targets production constants)

The harness stubs the GenVM web fetch and the LLM extraction call, so the
contract's own fetch plumbing, slicing, precedence rules and
deterministic Python delay/bucket math run for real.
"""
import calendar
import datetime
import json
import sys

import harness
from harness import (A, B, C, D, E, ZERO, UserError, call, conserve, DAY,
                     expect_err, fresh, set_time, stray)

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print("PASS", name)
    except Exception as e:  # noqa: BLE001
        FAIL.append((name, repr(e)))
        print("FAIL", name, "->", repr(e))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
GEN = 10 ** 18
T0 = calendar.timegm((2026, 11, 16, 0, 0, 0, 0, 0, 0))   # 2026-11-16 00:00 UTC
SDEP0 = T0 + 3 * DAY                                       # 2026-11-19 00:00 UTC
DUR = 62400                                                # 17h20m DXB->LAX
SARR0 = SDEP0 + DUR                                        # 2026-11-19 17:20 UTC
FDATE = "2026-11-19"
OPEN_T = SARR0 + 7200                                      # assessment opens
COV = 10 ** 17                                             # 0.1 GEN
PREM = COV * 1000 // 10000                                 # 0.01 GEN

U1 = "https://www.planemapper.com/flights/EK215"
U2 = "https://www.avionio.com/en/flight/ek-215"
BODY1 = b"<html><body>EK215 Dubai to Los Angeles flight status</body></html>"
BODY2 = b"<html><body>Emirates EK 215 flight status</body></html>"
LAX_OFF = -8 * 3600                                        # PST in November


def _local(unix, off_sec):
    t = datetime.datetime.utcfromtimestamp(unix + off_sec)
    return t.strftime("%H:%M"), t.strftime("%Y-%m-%d")


SCHED = {"scheduled_arrival_local": "09:20", "scheduled_date": "2026-11-19",
         "scheduled_tz_offset": "-08:00"}   # == SARR0 at LAX local time


def F(**kw):
    base = {"identity_ok": True, "date_shown": True, "status_class": "LANDED",
            "delay_minutes_shown": None, "actual_arrival_local": None,
            "arrival_date": None, "tz_offset": None,
            "scheduled_arrival_local": None, "scheduled_date": None,
            "scheduled_tz_offset": None, "sched_dep_local": None,
            "sched_dep_date": None, "sched_dep_tz_offset": None,
            "duration_minutes": None}
    base.update(kw)
    return base


def landed(delay_min, sched=True):
    clock, date = _local(SARR0 + delay_min * 60, LAX_OFF)
    d = F(actual_arrival_local=clock, arrival_date=date, tz_offset="-08:00",
          delay_minutes_shown=delay_min)
    if sched:
        d.update(SCHED)
    return d


def landed_schedoff(delay_min, delta_s):
    clock, date = _local(SARR0 + delta_s, LAX_OFF)
    d = landed(delay_min)
    d.update({"scheduled_arrival_local": clock, "scheduled_date": date,
              "scheduled_tz_offset": "-08:00"})
    return d


CANCELLED = F(status_class="CANCELLED")
CANCELLED_SCHED = F(status_class="CANCELLED", **SCHED)
NOT_LANDED = F(status_class="NOT_LANDED")
BADID = F(identity_ok=False)
NOTFOUND = F(date_shown=False)


def install(s1=None, s2=None, w1=(200, BODY1), w2=(200, BODY2)):
    """Install WEB bodies (None = unreachable) and per-source field stubs."""
    harness.WEB.clear()
    if w1 is not None:
        harness.WEB[U1] = w1
    if w2 is not None:
        harness.WEB[U2] = w2
    fields = {"S1": s1, "S2": s2}

    def fn(prompt, images):
        for tag in ("S1", "S2"):
            if ("From the " + tag + " page text") in prompt:
                v = fields[tag]
                assert v is not None, "extraction called for a down source"
                return v(prompt) if callable(v) else v
        raise AssertionError("source tag not found in prompt")

    harness.PROMPT_FN = fn


def mkpool(amt=GEN):
    c = fresh(0)
    set_time(T0)
    if amt:
        call(c, A, c.fund_pool, value=amt)
    return c


def buy(c, buyer=B, cov=COV, sdep=SDEP0, sarr=SARR0, fdate=FDATE, value=None,
        **idf):
    args = dict(al_iata="EK", al_name="Emirates", fno="215", dep="DXB",
                arr="LAX", dep_city="Dubai", arr_city="Los Angeles",
                fdate=fdate, sdep=sdep, sarr=sarr, cov=cov)
    args.update(idf)
    if value is None:
        value = args["cov"] * 1000 // 10000
    return int(call(c, buyer, c.buy_policy, args["al_iata"], args["al_name"],
                    args["fno"], args["dep"], args["arr"], args["dep_city"],
                    args["arr_city"], args["fdate"], args["sdep"],
                    args["sarr"], args["cov"], value=value))


def pol(c, pid):
    return json.loads(call(c, A, c.get_policy, pid))


def ov(c):
    return json.loads(call(c, A, c.get_overview))


def pot(c, addr):
    return int(call(c, A, c.get_claimable, addr))


def pend(c, addr):
    d = json.loads(call(c, A, c.get_pending, addr))
    return int(d["amt"]), int(d["since"])


def assess(c, pid, when=OPEN_T, sender=C):
    set_time(when)
    return call(c, sender, c.assess_policy, pid)


def gap(c, amt):
    """Balance sits exactly amt below the accounted total (landed pending)."""
    assert int(c.balance) == (int(c.poolf) + int(c.resw) + int(c.tcw)
                              + int(c.tpw) - amt), "gap mismatch"


def fdate_of(unix):
    return datetime.datetime.utcfromtimestamp(unix).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# §12 tests 1-11: funding, buying, cancelling, assessment gates
# ---------------------------------------------------------------------------
def t01():
    c = fresh(0)
    set_time(T0)
    expect_err(c, B, c.fund_pool, code="NOT_ADMIN", value=GEN)
    expect_err(c, A, c.fund_pool, code="BAD_AMOUNT", value=0)
    call(c, A, c.fund_pool, value=GEN)
    assert int(c.poolf) == GEN
    conserve(c)


def t02():
    c = mkpool()
    stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, COV, code="BAD_PREMIUM",
          value=PREM + 1)
    stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, COV, code="BAD_PREMIUM",
          value=PREM - 1)
    conserve(c)


def t03():
    c = mkpool()
    lo = 10 ** 16 - 1
    stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, lo, code="BAD_COVERAGE",
          value=lo * 1000 // 10000)
    hi = 10 ** 18 + 1
    stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, hi, code="BAD_COVERAGE",
          value=hi * 1000 // 10000)
    conserve(c)


def t04():
    c = mkpool(10 * GEN)

    def bad(sdep, sarr, fdate):
        stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX",
              "Dubai", "Los Angeles", fdate, sdep, sarr, COV,
              code="BAD_FLIGHT_TIME", value=PREM)

    bad(T0 + 86400, T0 + 86400 + DUR, fdate_of(T0 + 86400))     # lead == MIN_LEAD
    bad(SDEP0, SDEP0, FDATE)                                    # sarr <= sdep
    far_dep = T0 + 60 * DAY - 1800
    bad(far_dep, far_dep + 3600, fdate_of(far_dep))             # beyond horizon
    bad(SDEP0, SDEP0 + 899, FDATE)                              # duration < 900
    bad(SDEP0, SDEP0 + 86401, FDATE)                            # duration > 86400
    bad(SDEP0, SARR0, "2026-11-17")                             # fdate 2d early
    bad(SDEP0, SARR0, "2026-11-21")                             # fdate 2d late
    # controls: boundary durations and +-1 day fdate all succeed
    buy(c, fno="301", sarr=SDEP0 + 900)
    buy(c, fno="302", sarr=SDEP0 + 86400)
    buy(c, fno="303", fdate="2026-11-18")
    buy(c, fno="304", fdate="2026-11-20")
    conserve(c)


def t05():
    c = mkpool(10 * GEN)

    def bad2(al_iata="EK", al_name="Emirates", fno="215", dep="DXB",
             arr="LAX", dep_city="Dubai", arr_city="Los Angeles",
             fdate=FDATE):
        stray(c, B, c.buy_policy, al_iata, al_name, fno, dep, arr, dep_city,
              arr_city, fdate, SDEP0, SARR0, COV, code="BAD_FLIGHT",
              value=PREM)

    bad2(al_iata="E")
    bad2(al_iata="EKA")
    bad2(al_name="")
    bad2(al_name="!!!")
    bad2(fno="0")
    bad2(fno="21A")
    bad2(fno="0215")
    bad2(dep="DX")
    bad2(arr="DXB")
    bad2(dep_city="")
    bad2(arr_city="!!!")
    bad2(fdate="2026-13-01")
    bad2(fdate="19/11/2026")
    pid = buy(c, al_iata="ek")          # lowercase stored uppercased
    assert pol(c, pid)["al_iata"] == "EK"
    conserve(c)


def t06():
    c = mkpool(5 * 10 ** 16)            # 0.05 GEN pool, 0.1 GEN coverage
    stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, COV, code="POOL_INSUFFICIENT",
          value=PREM)
    assert int(c.poolf) == 5 * 10 ** 16
    conserve(c)


def t07():
    c = mkpool()
    cov, prem = 6 * 10 ** 16, 6 * 10 ** 15
    buy(c, B, cov=cov)
    buy(c, C, cov=cov)
    buy(c, D, cov=cov)
    buy(c, E, cov=cov)
    assert int(c.fxc["EK:215:2026-11-19"]) == 4 * cov
    stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, cov,
          code="FLIGHT_CAP_EXCEEDED", value=prem)
    # control A: same flight, different date -> different exposure key
    buy(c, B, cov=cov, sdep=SDEP0 + DAY, sarr=SARR0 + DAY, fdate="2026-11-20")
    # control B: settling one policy frees capacity for the blocked buy
    install(landed(200), landed(200))
    assess(c, 1)
    assert int(c.fxc.get("EK:215:2026-11-19", "0")) == 3 * cov
    set_time(T0)
    buy(c, C, cov=cov)
    conserve(c)


def t08():
    c = mkpool()
    call(c, A, c.set_paused, True)
    stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, COV, code="PAUSED", value=PREM)
    expect_err(c, B, c.set_paused, False, code="NOT_ADMIN")
    call(c, A, c.set_paused, False)
    assert ov(c)["paused"] is False
    conserve(c)


def t09():
    c = mkpool(10 * GEN)
    for i in range(10):
        buy(c, fno=str(215 + i))
    stray(c, B, c.buy_policy, "EK", "Emirates", "300", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, COV,
          code="TOO_MANY_POLICIES", value=PREM)
    install(landed(30), landed(30))
    assess(c, 1)                        # settles one -> slot frees
    set_time(T0)
    buy(c, fno="300")
    conserve(c)


def t10():
    c = mkpool(3 * GEN)
    pid1 = buy(c, fno="215")
    pid2 = buy(c, fno="300")
    pid3 = buy(c, fno="301")
    expect_err(c, C, c.cancel_policy, 999, code="POLICY_NOT_FOUND")
    expect_err(c, C, c.cancel_policy, pid1, code="NOT_BUYER")
    set_time(SARR0 + 604800 + 1)
    call(c, C, c.finalize_lapsed, pid2)
    expect_err(c, B, c.cancel_policy, pid2, code="BAD_STATE")   # lapsed
    set_time(SDEP0)
    expect_err(c, B, c.cancel_policy, pid3, code="BAD_STATE")   # at departure
    set_time(SDEP0 - 86400 + 3600)
    expect_err(c, B, c.cancel_policy, pid3, code="BAD_STATE")   # inside cutoff
    set_time(SDEP0 - 86400 - 1)
    call(c, B, c.cancel_policy, pid1)                           # happy path
    p = pol(c, pid1)
    assert p["st"] == "CANCELLED" and int(c.resw) == COV  # only pid3 reserved
    assert pot(c, B) == PREM            # full premium refunded to the pot
    assert "EK:215:2026-11-19" not in c.fxc
    expect_err(c, B, c.cancel_policy, pid1, code="BAD_STATE")   # twice
    conserve(c)


def t11():
    c = mkpool()
    pid = buy(c)
    expect_err(c, C, c.assess_policy, 999, code="POLICY_NOT_FOUND")
    set_time(SARR0 + 7199)
    expect_err(c, C, c.assess_policy, pid, code="TOO_EARLY")
    set_time(SARR0 + 604800 + 1)
    expect_err(c, C, c.assess_policy, pid, code="WINDOW_CLOSED")
    install(landed(30), landed(30))
    assess(c, pid)
    expect_err(c, C, c.assess_policy, pid, code="BAD_STATE")    # settled
    conserve(c)


# ---------------------------------------------------------------------------
# §12 tests 12-19: jury failure recording and the precedence matrix
# (v1.1: delta §3 steps 1-4; tests 12/15/18 rewritten per delta §6)
# ---------------------------------------------------------------------------
def _failed_assess(fields_kw, web_kw, token):
    c = mkpool()
    pid = buy(c)
    install(**fields_kw, **web_kw)
    r = assess(c, pid)
    assert r == token, r
    p = pol(c, pid)
    assert p["st"] == "OPEN" and p["fails"] == 1
    assert p["first_fail_at"] == str(OPEN_T) and p["last_fail"] == token
    assert int(c.tcw) == 0 and pot(c, B) == 0
    conserve(c)
    return c, pid


def t12():
    # all sources down -> EVIDENCE_UNAVAILABLE (delta §6 rewrite of the
    # v1 all-down case; assertions identical)
    _failed_assess({}, {"w1": None, "w2": None}, "EVIDENCE_UNAVAILABLE")


def t13():
    _failed_assess({"s1": landed(200)}, {"w2": (503, b"")},
                   "EVIDENCE_UNAVAILABLE")


def t14():
    _failed_assess({"s1": landed(200), "s2": CANCELLED}, {},
                   "EVIDENCE_UNAVAILABLE")


def t15():
    # (a) both sources show a different flight -> IDENTITY_MISMATCH
    _failed_assess({"s1": BADID, "s2": BADID}, {}, "IDENTITY_MISMATCH")
    # (b) right flight but date absent + one identity failure -> EU
    # (NOT_FOUND is unusable, never an identity failure: step 1 needs
    # BOTH sources to contradict the identity)
    _failed_assess({"s1": NOTFOUND, "s2": BADID}, {},
                   "EVIDENCE_UNAVAILABLE")
    # (c) one identity failure + one down -> EU
    _failed_assess({"s1": BADID}, {"w2": None}, "EVIDENCE_UNAVAILABLE")


def t16():
    off = landed_schedoff(200, 3600)
    _failed_assess({"s1": off, "s2": dict(off)}, {}, "SCHEDULE_MISMATCH")


def t17():
    c = mkpool()
    pid = buy(c)
    install(NOT_LANDED, NOT_LANDED)
    assert assess(c, pid) == "EVIDENCE_UNAVAILABLE"
    assert pol(c, pid)["st"] == "OPEN"
    install(landed(30), landed(30))
    assess(c, pid, when=OPEN_T + 3600)
    p = pol(c, pid)
    assert p["st"] == "NO_PAYOUT" and int(c.poolf) == GEN + PREM
    conserve(c)


def t18():
    # Delta §6 rewritten precedence matrix (steps 1-4 of delta §3).
    # (a) both sources identity-fail -> IDENTITY_MISMATCH (step 1 beats
    # any schedule question; with both sources badid no tuple exists)
    _failed_assess({"s1": BADID, "s2": BADID}, {}, "IDENTITY_MISMATCH")
    # (b) one usable source (schedule-failing) + one down -> EU
    # (step 2 beats step 4)
    _failed_assess({"s1": landed_schedoff(200, 3600)}, {"w2": None},
                   "EVIDENCE_UNAVAILABLE")
    # (c) tuple split (FULL/DELAY vs FULL/CANCELLATION) -> EU
    # (step 3 beats step 4)
    _failed_assess({"s1": landed_schedoff(200, 3600), "s2": CANCELLED_SCHED},
                   {}, "EVIDENCE_UNAVAILABLE")
    # (d) tuple agreement, both schedules 1h off -> SCHEDULE_MISMATCH
    off = landed_schedoff(200, 3600)
    _failed_assess({"s1": off, "s2": dict(off)}, {}, "SCHEDULE_MISMATCH")
    # (e) both usable reporting NOT_LANDED -> EU (step 2: no tuples)
    _failed_assess({"s1": NOT_LANDED, "s2": NOT_LANDED}, {},
                   "EVIDENCE_UNAVAILABLE")
    # (f) one NOT_LANDED + one FULL tuple -> EU (step 2: a single landed
    # reading never settles)
    _failed_assess({"s1": NOT_LANDED, "s2": landed(200)}, {},
                   "EVIDENCE_UNAVAILABLE")
    # (g) bucket-edge split: 58 min (NONE) vs 62 min (PARTIAL) -> EU
    # (step 3: exact-tuple agreement, no bucket tolerance)
    _failed_assess({"s1": landed(58), "s2": landed(62)}, {},
                   "EVIDENCE_UNAVAILABLE")
    # (h) agreed CANCELLATION, neither source prints a schedule ->
    # settles FULL (the cancelled-row rule passes step 4 vacuously)
    c = mkpool()
    pid = buy(c)
    install(CANCELLED, CANCELLED)
    r = json.loads(assess(c, pid))
    assert r == {"outcome": "FULL", "basis": "CANCELLATION",
                 "reason_code": "FLIGHT_CANCELLED"}, r
    assert pol(c, pid)["st"] == "PAID_FULL" and pot(c, B) == COV
    conserve(c)
    # (i) agreed CANCELLATION, one source prints a schedule 1h off ->
    # SCHEDULE_MISMATCH (a printed schedule must corroborate)
    full = F(status_class="CANCELLED")
    sched_off = landed_schedoff(0, 3600)
    full.update({k: sched_off[k] for k in ("scheduled_arrival_local",
                                           "scheduled_date",
                                           "scheduled_tz_offset")})
    _failed_assess({"s1": CANCELLED, "s2": full}, {}, "SCHEDULE_MISMATCH")
    # (j) asymmetric corroboration (non-cancelled): both agree NONE;
    # source 1's schedule matches sarr, source 2's is 1h off -> settles
    # NO_PAYOUT (step 4 needs only one corroborating usable source)
    c = mkpool()
    pid = buy(c)
    install(landed(30), landed_schedoff(30, 3600))
    r = json.loads(assess(c, pid))
    assert r == {"outcome": "NONE", "basis": "DELAY",
                 "reason_code": "ARRIVAL_DELAY_UNDER_60"}, r
    assert pol(c, pid)["st"] == "NO_PAYOUT"
    conserve(c)


def t19():
    c = mkpool()
    pid = buy(c)
    install(landed(200), landed(200))
    set_time(OPEN_T)
    harness.EQ_FN = lambda fn: ('{"outcome": "FULL", "basis": "DELAY", '
                                '"reason_code": "BOGUS"}')
    try:
        expect_err(c, C, c.assess_policy, pid, code="JURY_MALFORMED")
    finally:
        harness.EQ_FN = None
    set_time(OPEN_T)
    harness.EQ_FN = lambda fn: "this is not json"
    try:
        expect_err(c, C, c.assess_policy, pid, code="JURY_MALFORMED")
    finally:
        harness.EQ_FN = None
    assert pol(c, pid)["st"] == "OPEN" and int(c.tcw) == 0
    conserve(c)


# ---------------------------------------------------------------------------
# §12 tests 20-26: settlement branches, diversion, retries, lapse
# ---------------------------------------------------------------------------
def _settle(fields, expect_st):
    c = mkpool()
    pid = buy(c)
    web = {}
    for i, f in enumerate(fields):
        if f is None:
            web[f"w{i + 1}"] = None
    install(*fields, **web)
    r = json.loads(assess(c, pid))
    p = pol(c, pid)
    assert p["st"] == expect_st, p
    return c, pid, r, p


def t20():
    c, pid, r, p = _settle((landed(200), landed(200)), "PAID_FULL")
    assert r == {"outcome": "FULL", "basis": "DELAY",
                 "reason_code": "ARRIVAL_DELAY_180_OR_MORE"}
    assert int(p["payout"]) == COV and int(c.poolf) == 910_000_000_000_000_000
    assert int(c.resw) == 0 and pot(c, B) == COV
    assert "EK:215:2026-11-19" not in c.fxc and "1" not in c.obc
    expect_err(c, C, c.assess_policy, pid, code="BAD_STATE")
    call(c, B, c.claim_payout)
    call(c, B, c.confirm_withdrawal)
    assert int(c.balance) == int(c.poolf)
    conserve(c)


def t21():
    c, pid, r, p = _settle((landed(120), landed(120)), "PAID_PARTIAL")
    assert r["reason_code"] == "ARRIVAL_DELAY_60_TO_179"
    assert int(p["payout"]) == 25_000_000_000_000_000
    assert int(c.poolf) == 985_000_000_000_000_000 and pot(c, B) == 25 * 10 ** 15
    conserve(c)


def t22():
    c, pid, r, p = _settle((landed(30), landed(30)), "NO_PAYOUT")
    assert r == {"outcome": "NONE", "basis": "DELAY",
                 "reason_code": "ARRIVAL_DELAY_UNDER_60"}
    assert int(p["payout"]) == 0 and int(c.poolf) == GEN + PREM
    assert pot(c, B) == 0
    conserve(c)


def t23():
    c, pid, r, p = _settle((CANCELLED_SCHED, CANCELLED_SCHED), "PAID_FULL")
    assert r == {"outcome": "FULL", "basis": "CANCELLATION",
                 "reason_code": "FLIGHT_CANCELLED"}
    assert int(c.poolf) == 910_000_000_000_000_000 and pot(c, B) == COV
    conserve(c)


def t24():
    div = F(status_class="DIVERTED", **{k: landed(200)[k] for k in
                                       ("actual_arrival_local", "arrival_date",
                                        "tz_offset", "delay_minutes_shown")})
    div.update(SCHED)
    c, pid, r, p = _settle((div, dict(div)), "PAID_FULL")
    assert r["basis"] == "DELAY" and r["reason_code"] == "ARRIVAL_DELAY_180_OR_MORE"
    conserve(c)
    # diverted with no final arrival printed -> recorded failure
    nodiv = F(status_class="DIVERTED")
    _failed_assess({"s1": nodiv, "s2": dict(nodiv)}, {},
                   "EVIDENCE_UNAVAILABLE")
    # the DIVERSION basis / FLIGHT_DIVERTED reason never appear: every
    # settlement produced anywhere in this suite carries basis DELAY or
    # CANCELLATION (asserted per-test in t18f, t20-t24 via the verdict JSON)


def t25():
    c = mkpool()
    pid = buy(c)
    install(None, None, w1=None, w2=None)
    assert assess(c, pid, when=OPEN_T) == "EVIDENCE_UNAVAILABLE"
    install(BADID, BADID)
    assert assess(c, pid, when=OPEN_T + 100) == "IDENTITY_MISMATCH"
    p = pol(c, pid)
    assert p["fails"] == 2 and p["first_fail_at"] == str(OPEN_T)
    assert p["last_fail"] == "IDENTITY_MISMATCH"
    install(landed(30), landed(30))
    assess(c, pid, when=OPEN_T + 200)
    p = pol(c, pid)
    assert p["st"] == "NO_PAYOUT" and p["fails"] == 2
    assert p["assessed_at"] == str(OPEN_T + 200)
    conserve(c)


def t26():
    c = mkpool()
    pid = buy(c)
    expect_err(c, C, c.finalize_lapsed, 999, code="POLICY_NOT_FOUND")
    set_time(SARR0 + 604800)
    expect_err(c, C, c.finalize_lapsed, pid, code="WINDOW_OPEN")
    set_time(SARR0 + 604800 + 1)
    call(c, C, c.finalize_lapsed, pid)          # anyone may finalize
    p = pol(c, pid)
    assert p["st"] == "LAPSED" and int(c.resw) == 0
    assert int(c.poolf) == GEN + PREM           # premium kept by the pool
    expect_err(c, C, c.assess_policy, pid, code="BAD_STATE")
    conserve(c)


# ---------------------------------------------------------------------------
# §12 tests 27-38: pool withdrawal, the pull pattern, pause, ownership
# ---------------------------------------------------------------------------
def t27():
    c = mkpool()
    expect_err(c, B, c.withdraw_pool, 1, code="NOT_ADMIN")
    expect_err(c, A, c.withdraw_pool, 0, code="BAD_AMOUNT")
    expect_err(c, A, c.withdraw_pool, GEN + 1, code="POOL_INSUFFICIENT")
    pid = buy(c)
    expect_err(c, A, c.withdraw_pool, int(c.poolf) + 1,
               code="POOL_INSUFFICIENT")
    # drain the free pool into the admin pot; resw stays reserved
    amt = int(c.poolf)
    call(c, A, c.withdraw_pool, amt)
    assert int(c.poolf) == 0 and pot(c, A) == amt and int(c.resw) == COV
    expect_err(c, A, c.withdraw_pool, 1, code="POOL_INSUFFICIENT")
    conserve(c)
    # physical floor: with a landed-unconfirmed pending depressing the
    # balance, withdrawing the whole free pool leaves exactly resw + tcw
    # physically backed (the floor holds at equality), and one wei more is
    # stopped by the pool gate. NOTE: balance - poolf >= resw + tcw is an
    # accounting invariant of the pull pattern (every emission is counted
    # in tpw until it resolves), so the floor can only ever bind at
    # equality from reachable states; it is implemented verbatim as
    # defense-in-depth per spec SS6/SS9.
    c2 = mkpool(2 * GEN)
    pid2 = buy(c2)
    install(landed(120), landed(120))
    assess(c2, pid2)                            # PARTIAL: pot 25e15
    call(c2, B, c2.claim_payout)                # emission lands, unconfirmed
    gap(c2, 25 * 10 ** 15)
    free = int(c2.poolf)
    call(c2, A, c2.withdraw_pool, free)
    assert int(c2.balance) >= int(c2.resw) + int(c2.tcw)
    assert int(c2.balance) == (int(c2.poolf) + int(c2.resw) + int(c2.tcw)
                               + int(c2.tpw) - 25 * 10 ** 15)


def t28():
    c = mkpool()
    expect_err(c, B, c.claim_payout, code="NOTHING_CLAIMABLE")
    expect_err(c, B, c.confirm_withdrawal, code="NO_PENDING")
    pid = buy(c)
    install(landed(120), landed(120))
    assess(c, pid)
    call(c, B, c.claim_payout)
    expect_err(c, B, c.claim_payout, code="NOTHING_CLAIMABLE")  # double claim
    call(c, B, c.confirm_withdrawal)
    assert int(c.tpw) == 0
    conserve(c)


def t29():
    c = mkpool(2 * GEN)
    pid1 = buy(c, fno="215")
    sdep2 = SARR0 + 3 * DAY
    pid2 = buy(c, fno="215", sdep=sdep2, sarr=sdep2 + DUR,
               fdate=fdate_of(sdep2))
    install(landed(120), landed(120))
    assess(c, pid1)
    call(c, B, c.claim_payout)                  # pending 25e15, landed
    call(c, B, c.cancel_policy, pid2)           # refund credit, same pot
    assert pot(c, B) == PREM
    expect_err(c, B, c.claim_payout, code="PENDING_EXISTS")
    amt, since = pend(c, B)
    assert amt == 25 * 10 ** 15 and since == OPEN_T
    gap(c, 25 * 10 ** 15)


def t30():
    # the full double-payment drain script of SS12 test 30 / SS9
    c = mkpool(2 * GEN)
    pid1 = buy(c, fno="215")
    sdep2 = SARR0 + 3 * DAY
    pid2 = buy(c, fno="216", sdep=sdep2, sarr=sdep2 + DUR,
               fdate=fdate_of(sdep2))
    install(landed(200), landed(200))
    assess(c, pid1)                             # FULL: pot = COV
    set_time(OPEN_T)
    call(c, B, c.claim_payout)                  # pending COV in flight
    call(c, B, c.cancel_policy, pid2)           # refund credit tops the pot up
    assert pot(c, B) == PREM
    expect_err(c, B, c.claim_payout, code="PENDING_EXISTS")
    expect_err(c, B, c.restore_pending, code="PENDING_TOO_YOUNG")
    c.balance += 4 * 10 ** 16                   # stray transfer < pending
    expect_err(c, B, c.restore_pending, code="PENDING_TOO_YOUNG")
    # the emission lands: balance already dropped at claim; the books are
    # now short by exactly pending - stray (SS9 stray-restore bound)
    set_time(OPEN_T + 86400 + 1)
    expect_err(c, B, c.restore_pending, code="INSUFFICIENT_BACKING")
    call(c, B, c.confirm_withdrawal)            # payee keeps the landed COV
    conserve(c, dust=4 * 10 ** 16)              # stray stays locked, reported
    call(c, B, c.claim_payout)                  # remaining pot claims fine
    call(c, B, c.confirm_withdrawal)
    paid = sum(a for (to, a) in harness.TRANSFERS if to == B)
    assert paid == COV + PREM                   # each amount paid exactly once
    conserve(c, dust=4 * 10 ** 16)


def t31():
    c = mkpool()
    pid = buy(c)
    install(landed(120), landed(120))
    assess(c, pid)
    call(c, B, c.claim_payout)
    c.balance += 25 * 10 ** 15                  # emission still in flight
    expect_err(c, B, c.restore_pending, code="PENDING_TOO_YOUNG")
    amt, since = pend(c, B)
    assert amt == 25 * 10 ** 15 and since == OPEN_T
    conserve(c)


def t32():
    c = mkpool()
    pid = buy(c)
    install(landed(120), landed(120))
    assess(c, pid)
    call(c, B, c.claim_payout)
    c.balance += 25 * 10 ** 15                  # stranded: never landed
    set_time(OPEN_T + 86400 + 1)
    call(c, B, c.restore_pending)               # honest restore succeeds
    assert pot(c, B) == 25 * 10 ** 15
    assert pend(c, B) == (0, 0)
    conserve(c)


def t33():
    c = mkpool()
    pid = buy(c)
    install(landed(120), landed(120))
    assess(c, pid)
    call(c, B, c.claim_payout)                  # lands, never confirmed
    set_time(OPEN_T + 86400 + 1)
    expect_err(c, B, c.restore_pending, code="INSUFFICIENT_BACKING")
    amt, since = pend(c, B)
    assert amt == 25 * 10 ** 15 and since == OPEN_T
    gap(c, 25 * 10 ** 15)


def t34():
    c = mkpool(3 * GEN)
    pidb = buy(c, B)
    pidc = buy(c, C)                            # same flight, second buyer
    install(landed(120), landed(120))
    assess(c, pidb)
    assess(c, pidc)
    call(c, B, c.claim_payout)                  # B's emission lands
    call(c, C, c.claim_payout)
    c.balance += 25 * 10 ** 15                  # C's emission stranded
    set_time(OPEN_T + 86400 + 1)
    expect_err(c, B, c.restore_pending, code="INSUFFICIENT_BACKING")
    call(c, B, c.confirm_withdrawal)
    call(c, C, c.restore_pending)               # now backed: succeeds
    assert pot(c, C) == 25 * 10 ** 15
    conserve(c)


def _writeoff_setup(landed_emission=True):
    c = mkpool()
    pid = buy(c)
    install(landed(120), landed(120))
    assess(c, pid)
    call(c, B, c.claim_payout)
    if not landed_emission:
        c.balance += 25 * 10 ** 15              # stranded
    return c


def t35():
    c = _writeoff_setup()
    set_time(OPEN_T + 604800 - 1)
    expect_err(c, B, c.write_off_pending, B, code="PENDING_TOO_YOUNG")
    set_time(OPEN_T + 604800 + 1)
    expect_err(c, D, c.write_off_pending, B, code="NOT_PAYEE")
    expect_err(c, C, c.write_off_pending, C, code="NO_PENDING")
    c2 = _writeoff_setup(landed_emission=False)  # stranded: no shortfall
    set_time(OPEN_T + 604800 + 1)
    expect_err(c2, B, c2.write_off_pending, B, code="NO_SHORTFALL")
    amt, _ = pend(c2, B)
    assert amt == 25 * 10 ** 15
    conserve(c2)


def t36():
    for caller in (B, A):                       # payee- and admin-initiated
        c = _writeoff_setup()
        set_time(OPEN_T + 604800 + 1)
        call(c, caller, c.write_off_pending, B)
        assert pend(c, B) == (0, 0) and int(c.tpw) == 0
        assert int(c.wo) == 25 * 10 ** 15
        assert pot(c, B) == 0                   # never re-credited
        conserve(c)                             # balance == accounted again


def t37():
    c = mkpool(3 * GEN)
    pid1 = buy(c)
    pid2 = buy(c)
    pid3 = buy(c)
    pidc = buy(c, C)                            # all on the same EK215 flight
    call(c, A, c.set_paused, True)
    call(c, B, c.cancel_policy, pid1)           # cancel works while paused
    call(c, A, c.fund_pool, value=GEN)          # funding works while paused
    call(c, A, c.withdraw_pool, 10 ** 15)       # withdrawal works while paused
    install(landed(120), landed(120))
    assess(c, pid2)                             # assessment works while paused
    call(c, B, c.claim_payout)                  # pot operations work paused
    call(c, B, c.confirm_withdrawal)
    assess(c, pidc)
    call(c, C, c.claim_payout)
    c.balance += 25 * 10 ** 15                  # C's emission stranded
    set_time(OPEN_T + 86400 + 1)
    call(c, C, c.restore_pending)               # restore works while paused
    expect_err(c, C, c.finalize_lapsed, pid3, code="WINDOW_OPEN")
    call(c, A, c.set_paused, False)
    conserve(c)


def t38():
    c = mkpool()
    expect_err(c, B, c.transfer_ownership, D, code="NOT_ADMIN")
    expect_err(c, A, c.transfer_ownership, ZERO, code="BAD_ADDRESS")
    expect_err(c, A, c.transfer_ownership, "0x123", code="BAD_ADDRESS")
    expect_err(c, A, c.transfer_ownership, A, code="BAD_ADDRESS")
    expect_err(c, D, c.accept_ownership, code="NO_PENDING_ADMIN")
    call(c, A, c.transfer_ownership, D)
    expect_err(c, E, c.accept_ownership, code="NO_PENDING_ADMIN")
    call(c, D, c.accept_ownership)
    assert c.own == D and c.pown == ""
    expect_err(c, D, c.accept_ownership, code="NO_PENDING_ADMIN")
    call(c, D, c.transfer_ownership, E)         # overwrite: stage E...
    call(c, D, c.transfer_ownership, B)         # ...then replace with B
    expect_err(c, E, c.accept_ownership, code="NO_PENDING_ADMIN")
    call(c, B, c.accept_ownership)
    assert c.own == B
    conserve(c)


# ---------------------------------------------------------------------------
# §12 tests 39-42: strays, wei exactness, value-on-non-payable, worked example
# ---------------------------------------------------------------------------
def t39():
    c = mkpool()
    bal0 = int(c.balance)
    try:
        call(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX",
             "Dubai", "Los Angeles", FDATE, SDEP0, SARR0, COV,
             value=PREM + 7)
        raise AssertionError("buy should have reverted")
    except UserError as e:
        assert str(e) == "BAD_PREMIUM"
    o = ov(c)
    # the rejected premium sits in the physical balance, visible in the
    # overview as an unaccounted stray, never absorbed into any counter
    assert int(o["contract_balance_wei"]) == bal0 + PREM + 7
    assert int(o["poolf"]) == GEN and int(o["tcw"]) == 0
    assert len(c.pols) == 0
    c.balance -= PREM + 7                       # model the sender taking it back
    conserve(c)


def t40():
    cov = 10_000_000_000_000_003                # 0.01 GEN + 3 wei
    prem = 1_000_000_000_000_000                # floor(cov * 10%) exactly
    c = mkpool()
    pid = buy(c, cov=cov, value=prem)
    p = pol(c, pid)
    assert int(p["prem"]) == prem and int(p["cov"]) == cov
    install(landed(120), landed(120))
    assess(c, pid)
    p = pol(c, pid)
    assert int(p["payout"]) == 2_500_000_000_000_000   # floor(cov * 25%)
    set_time(T0)
    pid2 = buy(c, cov=cov, value=prem, fno="216")
    call(c, B, c.cancel_policy, pid2)
    assert pot(c, B) == 2_500_000_000_000_000 + prem  # exact refund, no dust
    call(c, B, c.claim_payout)
    call(c, B, c.confirm_withdrawal)
    conserve(c)                                 # exact to the wei, dust = 0


def t41():
    c = mkpool()
    pid = buy(c)
    install(landed(120), landed(120))
    assess(c, pid)                              # B now has a pot
    set_time(T0)
    pid2 = buy(c, fno="216")
    for fn, args, sender in (
            (c.cancel_policy, (pid2,), B),
            (c.assess_policy, (pid2,), C),
            (c.claim_payout, (), B),
            (c.withdraw_pool, (1,), A),
            (c.set_paused, (True,), A)):
        expect_err(c, sender, fn, *args, code="BAD_AMOUNT", value=100)
    assert pend(c, B) == (0, 0)                 # no pending was created
    assert pot(c, B) == 25 * 10 ** 15           # pot untouched
    conserve(c)


def _branch(kind):
    c = mkpool()
    pid = buy(c)
    if kind == "CANCELLED":
        call(c, B, c.cancel_policy, pid)
        call(c, B, c.claim_payout)
        call(c, B, c.confirm_withdrawal)
        return c
    if kind == "LAPSED":
        set_time(SARR0 + 604800 + 1)
        call(c, C, c.finalize_lapsed, pid)
        return c
    fields = {"FULL": landed(200), "PARTIAL": landed(120),
              "NONE": landed(30)}[kind]
    install(fields, fields)
    assess(c, pid)
    if kind in ("FULL", "PARTIAL"):
        call(c, B, c.claim_payout)
        call(c, B, c.confirm_withdrawal)
    return c


def t42():
    ends = {}
    c = _branch("FULL")
    assert int(c.poolf) == 910_000_000_000_000_000
    ends["FULL"] = int(c.balance)
    c = _branch("PARTIAL")
    assert int(c.poolf) == 985_000_000_000_000_000
    ends["PARTIAL"] = int(c.balance)
    c = _branch("NONE")
    assert int(c.poolf) == 1_010_000_000_000_000_000
    ends["NONE"] = int(c.balance)
    c = _branch("LAPSED")
    assert int(c.poolf) == 1_010_000_000_000_000_000
    ends["LAPSED"] = int(c.balance)
    c = _branch("CANCELLED")
    assert int(c.poolf) == GEN and int(c.balance) == GEN
    ends["CANCELLED"] = int(c.balance)
    # the five end states sum to funding + premiums - payouts, to the wei
    total_in = 5 * GEN + 5 * PREM
    total_out = COV + 25 * 10 ** 15 + PREM      # FULL + PARTIAL + refund
    assert sum(ends.values()) == total_in - total_out
    # SS9 underwriting control at the worked example's scale
    c = mkpool(5 * 10 ** 16)
    stray(c, B, c.buy_policy, "EK", "Emirates", "215", "DXB", "LAX", "Dubai",
          "Los Angeles", FDATE, SDEP0, SARR0, COV, code="POOL_INSUFFICIENT",
          value=PREM)


# ---------------------------------------------------------------------------
# Delta §6 new tests 43-45: templates, slicing/anchoring, non-tuple guards
# ---------------------------------------------------------------------------
def t43():
    # Template construction: the jury requests exactly the two committed
    # templates, built from the stored policy fields (PlaneMapper takes
    # the stored uppercased al_iata concatenated with fno; Avionio takes
    # al_iata lowercased at build time, one hyphen, fno). WEB is
    # installed only at those URLs, so a wrong URL fails the fetch.
    c = mkpool(10 * GEN)
    pid = buy(c, al_iata="ek")            # stored uppercased as "EK"
    assert pol(c, pid)["al_iata"] == "EK"
    install(landed(30), landed(30))
    harness.URLS.clear()
    assess(c, pid)
    assert harness.URLS == ["https://www.planemapper.com/flights/EK215",
                            "https://www.avionio.com/en/flight/ek-215"], \
        harness.URLS
    # a second flight number: no separator on PlaneMapper, exactly one
    # hyphen on Avionio, and no city or airline-name slug in either URL
    set_time(T0)
    pid2 = buy(c, fno="201")
    install(landed(30), landed(30))
    harness.WEB["https://www.planemapper.com/flights/EK201"] = (200, BODY1)
    harness.WEB["https://www.avionio.com/en/flight/ek-201"] = (200, BODY2)
    harness.URLS.clear()
    assess(c, pid2)
    assert harness.URLS == ["https://www.planemapper.com/flights/EK201",
                            "https://www.avionio.com/en/flight/ek-201"], \
        harness.URLS
    for u in harness.URLS:
        lu = u.lower()
        assert "dubai" not in lu and "los-angeles" not in lu
        assert "emirates" not in lu
    conserve(c)


def _big_page(header, row):
    """A page whose stripped text carries the flight/route header first
    and the fdate row past char 16,000 (the real PlaneMapper history
    layout). Returns (body bytes, plain text)."""
    filler = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do "
    parts = [header + " "]
    total = len(parts[0])
    while total < 16000:
        parts.append(filler)
        total += len(filler)
    parts.append(row + " ")
    total += len(row) + 1
    while total < 30000:
        parts.append(filler)
        total += len(filler)
    text = "".join(parts)
    return ("<html><body>" + text + "</body></html>").encode(), text


def t44():
    hdr = "EK215 Emirates Dubai DXB to Los Angeles LAX flight status history"
    row_pm = ("EK215 Dubai DXB Los Angeles LAX Thu, 19 Nov scheduled 09:20 "
              "PST estimated 08:47 PST")
    row_av = ("EK215 Dubai DXB Los Angeles LAX 19 Nov 2026 scheduled 09:20 "
              "landed 08:47")
    seen = {}

    def fn(prompt, images):
        page = prompt.split("\nPAGE:\n", 1)[1]
        for tag in ("S1", "S2"):
            if ("From the " + tag + " page text") in prompt:
                seen[tag] = page
                if "EK215" not in page:
                    return F(identity_ok=False)
                if "19 Nov" not in page:
                    return F(identity_ok=True, date_shown=False)
                if tag == "S1":
                    # PlaneMapper shape: named zone abbreviations, and
                    # no arrival date printed in history rows
                    return F(actual_arrival_local="08:47",
                             scheduled_arrival_local="09:20",
                             scheduled_date="2026-11-19",
                             scheduled_tz_offset="PST", tz_offset="PST",
                             delay_minutes_shown=-33)
                # Avionio shape: bare local times, no timezone anywhere;
                # the offset is derived from the printed schedule (rule b)
                return F(actual_arrival_local="08:47",
                         scheduled_arrival_local="09:20",
                         scheduled_date="2026-11-19",
                         delay_minutes_shown=-33)
        raise AssertionError("source tag not found in prompt")

    # (a) header + anchoring: with the date row past char 16,000 the
    # jury slice still carries the header AND the row, and the two
    # source shapes agree on NONE (EK215 landed 33 min early).
    c = mkpool()
    pid = buy(c)
    body1, text1 = _big_page(hdr, row_pm)
    body2, text2 = _big_page(hdr, row_av)
    assert text1.find("Thu, 19 Nov") > 15000
    assert text2.find("19 Nov 2026") > 15000
    harness.WEB.clear()
    harness.WEB[U1] = (200, body1)
    harness.WEB[U2] = (200, body2)
    harness.PROMPT_FN = fn
    r = json.loads(assess(c, pid))
    assert r == {"outcome": "NONE", "basis": "DELAY",
                 "reason_code": "ARRIVAL_DELAY_UNDER_60"}, r
    for tag in ("S1", "S2"):
        page = seen[tag]
        assert len(page) <= 6000, len(page)
        assert "EK215" in page[:1500]          # header prefix retained
        assert "19 Nov" in page                # the fdate row is present
    assert pol(c, pid)["st"] == "NO_PAYOUT"
    conserve(c)

    # (b) anchor miss -> the head slice still reaches the LLM: a wrong
    # flight on both pages yields IDENTITY_MISMATCH (step 1 reachable),
    # and the right flight with no date row yields NOT_FOUND -> EU.
    c = mkpool()
    pid = buy(c)
    wrong = "BA117 British Airways London LHR to New York JFK flight status"
    body1, _ = _big_page(wrong, "some other row entirely")
    body2, _ = _big_page(wrong, "some other row entirely")
    harness.WEB.clear()
    harness.WEB[U1] = (200, body1)
    harness.WEB[U2] = (200, body2)
    harness.PROMPT_FN = fn
    assert assess(c, pid) == "IDENTITY_MISMATCH"
    body1, _ = _big_page(hdr, "a row with no date in it")
    body2, _ = _big_page(hdr, "a row with no date in it")
    harness.WEB.clear()
    harness.WEB[U1] = (200, body1)
    harness.WEB[U2] = (200, body2)
    assert assess(c, pid, when=OPEN_T + 100) == "EVIDENCE_UNAVAILABLE"
    p = pol(c, pid)
    assert p["st"] == "OPEN" and p["fails"] == 2
    conserve(c)


def t45():
    # Mixed non-tuple guards: no settlement may ever come out of fewer
    # than two valid tuples.
    # (a) PlaneMapper LANDED (FULL tuple) + Avionio departure-only row
    # (NOT_LANDED, no arrival) -> EU at step 2
    _failed_assess({"s1": landed(200), "s2": NOT_LANDED}, {},
                   "EVIDENCE_UNAVAILABLE")
    # (b) NOT_LANDED + DIVERTED with no printed final arrival: both
    # yield no tuple -> EU; None == None never settles
    nodiv = F(status_class="DIVERTED")
    _failed_assess({"s1": NOT_LANDED, "s2": nodiv}, {},
                   "EVIDENCE_UNAVAILABLE")
    # (c) LANDED with actual_arrival_local null and delay_minutes_shown
    # null (no tuple) + a FULL tuple -> EU at step 2
    _failed_assess({"s1": F(), "s2": landed(200)}, {},
                   "EVIDENCE_UNAVAILABLE")


def t46():
    # Amendment A1 (delta §6 test 46): a rule-(b) derived schedule never
    # corroborates the committed sarr — corroboration must come from a
    # schedule computed from a printed offset. EK215 shapes throughout:
    # PlaneMapper-style legs print named-zone times at the TRUE schedule
    # (09:20 PST == SARR0); Avionio-style legs print bare local times, so
    # their offset is derived from the committed sarr itself.
    sched_clock, sched_date = _local(SARR0, LAX_OFF)

    def pm_landed(delay_min):
        clock, date = _local(SARR0 + delay_min * 60, LAX_OFF)
        return F(actual_arrival_local=clock, arrival_date=date,
                 tz_offset="PST", delay_minutes_shown=delay_min,
                 scheduled_arrival_local=sched_clock,
                 scheduled_date=sched_date, scheduled_tz_offset="PST")

    def av_landed(delay_min):
        clock, date = _local(SARR0 + delay_min * 60, LAX_OFF)
        return F(actual_arrival_local=clock, arrival_date=date,
                 delay_minutes_shown=delay_min,
                 scheduled_arrival_local=sched_clock,
                 scheduled_date=sched_date)

    def failed_fake(sarr, s1, s2):
        c = mkpool()
        pid = buy(c, sarr=sarr)
        install(s1, s2)
        assert assess(c, pid) == "SCHEDULE_MISMATCH"
        p = pol(c, pid)
        assert p["st"] == "OPEN" and p["fails"] == 1
        assert p["first_fail_at"] == str(OPEN_T)
        assert p["last_fail"] == "SCHEDULE_MISMATCH"
        assert int(c.tcw) == 0 and pot(c, B) == 0
        conserve(c)

    # (a) sarr faked exactly 4h00m early: Avionio's derived schedule
    # lands exactly on the fake (pre-A1 this settled NONE); PlaneMapper's
    # printed schedule is 4h away -> no independent corroboration.
    failed_fake(SARR0 - 14400, pm_landed(30), av_landed(30))
    # (a2) the fake at 4h04m early sits inside derivation's +/-300 s
    # acceptance band around the grid point, so Avionio still derives a
    # schedule from it -> still SCHEDULE_MISMATCH.
    failed_fake(SARR0 - 14640, pm_landed(30), av_landed(30))
    # (b) honest control: the (a) fixture with the true sarr settles on
    # the agreed tuple (PlaneMapper corroborates independently).
    c = mkpool()
    pid = buy(c)
    install(pm_landed(30), av_landed(30))
    r = json.loads(assess(c, pid))
    assert r == {"outcome": "NONE", "basis": "DELAY",
                 "reason_code": "ARRIVAL_DELAY_UNDER_60"}, r
    assert pol(c, pid)["st"] == "NO_PAYOUT" and pot(c, B) == 0
    conserve(c)
    # (c1) agreed CANCELLATION; PlaneMapper prints the true schedule
    # (non-derived, 4h from the faked sarr), Avionio CANCELLED bare-local
    # deriving from the fake -> SCHEDULE_MISMATCH.
    pm_cx = F(status_class="CANCELLED", scheduled_arrival_local=sched_clock,
              scheduled_date=sched_date, scheduled_tz_offset="PST")
    av_cx = F(status_class="CANCELLED", scheduled_arrival_local=sched_clock,
              scheduled_date=sched_date)
    failed_fake(SARR0 - 14400, pm_cx, av_cx)
    # (c2) agreed CANCELLATION; PlaneMapper prints NO scheduled arrival,
    # Avionio prints a bare-local one whose derivation FAILS (sarr faked
    # 4h07m early, the inter-grid dead zone) -> SCHEDULE_MISMATCH: a
    # schedule was printed, so the vacuous pass must not fire.
    av_cx_dead = F(status_class="CANCELLED",
                   scheduled_arrival_local=sched_clock,
                   scheduled_date=sched_date)
    failed_fake(SARR0 - 14820, CANCELLED, av_cx_dead)
    # (d) both sources bare-local on a DELAY tuple, honest sarr: only
    # derived schedules exist -> SCHEDULE_MISMATCH (no fallback for
    # DELAY tuples).
    failed_fake(SARR0, av_landed(30), av_landed(30))


TESTS = [(f"t{i:02d}", globals()[f"t{i:02d}"]) for i in range(1, 47)]

if __name__ == "__main__":
    for name, fn in TESTS:
        check(name, fn)
    print(f"\n{len(PASS)}/{len(TESTS)} PASS")
    if FAIL:
        print("FAILURES:")
        for n, e in FAIL:
            print(" ", n, e)
        sys.exit(1)
