# v0.3.0
# { "Depends": "py-genlayer:babwp9t37jw9g4j2bccgn14g6x7x9s1f7dsmh7emvz735pz4zxa0" }
import genlayer as gl
from genlayer.storage import TreeMap
from genlayer.types import Address, u256, bigint
import json
import re

_UE = gl.vm.UserError
jd = json.dumps
jl = json.loads
# FlightCover v1.1 (SPEC.md as amended by SPEC-v1.1-delta.md, both frozen
# 2026-11-20): parametric flight-delay insurance. A GEN pool sells
# policies on specific flights at a premium of 10% of coverage, reserving
# the full coverage 1:1 at sale. After arrival, anyone triggers
# assessment: an AI jury reads the flight's real outcome from two public
# status sources (PlaneMapper and Avionio) whose URL templates are
# committed in this code, returns only an outcome bucket, and
# deterministic code pays by a fixed ladder (FULL 100%, PARTIAL 25%,
# NONE 0%). The buyer files nothing, ever. Payouts use the house pull
# pattern: claim_payout refuses while a pending exists (PENDING_EXISTS),
# restore_pending is age-gated and backing-gated, and write_off_pending
# extinguishes a landed-but-unconfirmed pending only against a real
# shortfall (NO_SHORTFALL).
PREMIUM_BPS = 1000
FLIGHT_CAP_BPS = 2500
MIN_COV = 10000000000000000
MAX_COV = 1000000000000000000
MAX_OPEN = 10
MIN_LEAD = 86400
CANCEL_CUTOFF = 86400
MAX_HORIZON = 5184000
ASSESS_OPEN_LAG = 7200
ASSESS_SPAN = 604800
SCHED_TOLERANCE = 300
RESTORE_DELAY = 86400
WRITEOFF_DELAY = 604800
LADDER = {"FULL": 10000, "PARTIAL": 2500, "NONE": 0}
_SETTLE_ST = {"FULL": "PAID_FULL", "PARTIAL": "PAID_PARTIAL", "NONE": "NO_PAYOUT"}
_OUTCOMES = ["NONE", "PARTIAL", "FULL"]
_BASES = ["DELAY", "CANCELLATION", "DIVERSION"]
_REASONS = ["ARRIVAL_DELAY_UNDER_60", "ARRIVAL_DELAY_60_TO_179",
            "ARRIVAL_DELAY_180_OR_MORE", "FLIGHT_CANCELLED", "FLIGHT_DIVERTED"]
_PAIRS = {("NONE", "DELAY"): "ARRIVAL_DELAY_UNDER_60",
          ("PARTIAL", "DELAY"): "ARRIVAL_DELAY_60_TO_179",
          ("FULL", "DELAY"): "ARRIVAL_DELAY_180_OR_MORE",
          ("FULL", "CANCELLATION"): "FLIGHT_CANCELLED",
          ("FULL", "DIVERSION"): "FLIGHT_DIVERTED"}
_TOKENS = ["EVIDENCE_UNAVAILABLE", "IDENTITY_MISMATCH", "SCHEDULE_MISMATCH"]
_AZ = "abcdefghijklmnopqrstuvwxyz"
_HEX = "0123456789abcdef"
_ADIG = "0123456789"
_WD = ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"]
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Named zone abbreviations printed by PlaneMapper arrival columns (delta
# SS4 rule (a)): fixed standard/daylight offsets in seconds. US zones plus
# the Pacific/Atlantic zone abbreviations PlaneMapper uses.
_ZONES = {"PST": -28800, "PDT": -25200, "MST": -25200, "MDT": -21600,
          "CST": -21600, "CDT": -18000, "EST": -18000, "EDT": -14400,
          "AKST": -32400, "AKDT": -28800, "HST": -36000, "SST": -39600,
          "CHST": 36000}


def _cj(o) -> str:
  return jd(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _days(y: int, m: int, d: int) -> int:
  y -= 1 if m <= 2 else 0
  era = (y if y >= 0 else y - 399) // 400
  yoe = y - era * 400
  return era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + (153 * ((m + 9) % 12) + 2) // 5 + d - 1 - 719468


def _civil(z: int):
  z += 719468
  era = (z if z >= 0 else z - 146096) // 146097
  doe = z - era * 146097
  yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
  y = yoe + era * 400
  doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
  mp = (5 * doy + 2) // 153
  d = doy - (153 * mp + 2) // 5 + 1
  m = mp + 3 if mp < 10 else mp - 9
  return (y + (1 if m <= 2 else 0), m, d)


def _now_unix() -> int:
  s = str(gl.message.datetime)
  if len(s) < 19 or s[4] != "-" or s[7] != "-" or s[10] != "T" or s[13] != ":" or s[16] != ":":
    raise ValueError("bad datetime")
  yy, mo, dd, hh, mi, ss = int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19])
  if not (1 <= mo <= 12 and 1 <= dd <= 31 and hh < 24 and mi < 60 and ss < 60):
    raise ValueError("bad datetime")
  return _days(yy, mo, dd) * 86400 + hh * 3600 + mi * 60 + ss


def _valid_addr(a: str) -> bool:
  return len(a) == 42 and a.startswith("0x") and a != "0x" + "0" * 40 and all(c in _HEX for c in a[2:])


def _slug(s) -> str:
  out = []
  for ch in str(s).lower():
    if ch == " ":
      out.append("-")
    elif ch in _AZ or ch.isdigit() or ch == "-":
      out.append(ch)
  return re.sub(r"-+", "-", "".join(out))


def _slug_ok(s) -> bool:
  # v1.1 identity hygiene (delta SS2): the normalized form must contain
  # at least one ASCII alphanumeric. v1 required only a non-empty slug,
  # which a name like "---" satisfied (it normalizes to "-"); the
  # tightening is deliberate and recorded in the delta.
  return any(c in _AZ or c in _ADIG for c in _slug(s))


def _dim(y: int, m: int) -> int:
  if m == 2:
    return 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
  return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def _pdate(s):
  # "YYYY-MM-DD" -> days since epoch, or None.
  if not isinstance(s, str) or len(s) != 10 or s[4] != "-" or s[7] != "-":
    return None
  try:
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
  except Exception:
    return None
  if not (1 <= m <= 12 and 1 <= d <= _dim(y, m)):
    return None
  return _days(y, m, d)


def _clock(s):
  # "HH:MM" or "HH:MM:SS" -> seconds into the day, or None.
  if not isinstance(s, str):
    return None
  m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s.strip())
  if not m:
    return None
  h, mi, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
  if h >= 24 or mi >= 60 or ss >= 60:
    return None
  return h * 3600 + mi * 60 + ss


def _poff(s):
  # A printed UTC offset ("+05:30", "-0800", "UTC+5", "Z") or a named zone
  # abbreviation ("PST", "EDT", ...) -> seconds, or None.
  if s is None:
    return None
  t = str(s).strip().upper().replace("UTC", "").replace("GMT", "").strip()
  if t in ("", "Z"):
    return 0
  if t in _ZONES:
    return _ZONES[t]
  m = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", t)
  if not m:
    return None
  v = int(m.group(2)) * 3600 + int(m.group(3) or 0) * 60
  return v if m.group(1) == "+" else -v


def _strip_html(t: str) -> str:
  t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
  t = re.sub(r"(?s)<[^>]+>", " ", t)
  t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
  return re.sub(r"\s+", " ", t)


def _fetch(url: str):
  # Unwrap the Response and strip markup BEFORE slicing (markup must not
  # eat the evidence). Returns the full stripped text; slicing is a
  # separate deterministic step (_slice).
  try:
    res = gl.nondet.web.get(url)
    status = getattr(res, "status", None)
    if isinstance(status, int) and status != 200:
      return None
    body = res if isinstance(res, (bytes, bytearray)) else res.body
    if not isinstance(body, (bytes, bytearray)) or len(body) == 0:
      return None
    return _strip_html(bytes(body).decode("utf-8", "replace"))
  except Exception:
    return None


def _anchors(fdate: str):
  # The exact per-source date strings, derived mechanically from fdate
  # (delta SS2/SS4): PlaneMapper prints "Thu, 19 Nov" (weekday abbrev,
  # zero-padded day, month abbrev, no year); Avionio prints
  # "19 Nov 2026". Day 0 (1970-01-01) was a Thursday.
  d = _pdate(fdate)
  if d is None:
    return None, None
  _y, m, dd = _civil(d)
  pm = _WD[d % 7] + ", " + ("%02d" % dd) + " " + _MON[m - 1]
  av = ("%02d" % dd) + " " + _MON[m - 1] + " " + str(_y)
  return pm, av


def _slice(text: str, anchor) -> str:
  # The 6,000-char jury slice (delta SS2): a 1,500-char header prefix
  # (the page's flight/route header) plus a 4,500-char window starting
  # ~200 chars before the policy date's row, deduplicated when the two
  # parts overlap. If the anchor cannot locate the date row, the head
  # slice (first 6,000 chars) goes to the LLM instead: NOT_FOUND is an
  # extraction outcome, never a pre-LLM short-circuit.
  if anchor is None:
    return text[:6000]
  i = text.find(anchor)
  if i < 0:
    return text[:6000]
  start = i - 200
  if start <= 1500:
    return text[:6000]
  return text[:1500] + text[start:start + 4500]


def _extract(pol, tag: str, text: str):
  guide = ""
  if tag == "S1":
    guide = (" This is the PlaneMapper page: it prints no status words. Its arrival "
             "column is headed 'Estimated'; for the flight-date row, a filled Estimated "
             "arrival cell means the flight landed and that time is the arrival of "
             "record (report status_class LANDED and that time as actual_arrival_local); "
             "an empty Estimated cell means no arrival is recorded (report NOT_LANDED "
             "with actual_arrival_local null) - never infer CANCELLED from empty cells. "
             "tz_offset: the zone abbreviation the page prints for arrival times "
             "(e.g. PST), else null.")
  elif tag == "S2":
    guide = (" This is the Avionio page: each row prints a status text. 'Landed HH:MM' "
             "is LANDED with that actual arrival; 'Departed HH:MM' means the row never "
             "received a landed time (report NOT_LANDED with actual_arrival_local "
             "null) - never infer an arrival from a departure-only row, and never "
             "substitute another date's row. The page prints no timezone, so "
             "tz_offset is null.")
  prompt = (
    "Extract flight-status fields as JSON only, copying values exactly as printed; "
    "do no arithmetic and no timezone conversion. Flight: " + pol["al_iata"] + pol["fno"] +
    " (" + pol["al_name"] + "), route " + pol["dep"] + " to " + pol["arr"] +
    ", flight date " + pol["fdate"] + ". From the " + tag + " page text report: "
    "identity_ok (page is about this airline, flight number and route, any date - judge identity on the IATA codes, not on exact airline or city name spellings); "
    "date_shown (page shows this flight on the flight date); "
    "status_class (LANDED, CANCELLED, DIVERTED, NOT_LANDED or NOT_FOUND); "
    "delay_minutes_shown (explicit delay minutes printed for that date, else null); "
    "actual_arrival_local (HH:MM at destination for that date, else null); "
    "arrival_date (YYYY-MM-DD of that arrival, else null); "
    "tz_offset (UTC offset the page names for arrival times, e.g. +05:30, else null); "
    "scheduled_arrival_local, scheduled_date, scheduled_tz_offset (scheduled arrival for that date if printed, else null); "
    "sched_dep_local, sched_dep_date, sched_dep_tz_offset, duration_minutes (printed scheduled departure and scheduled duration in minutes, else null)."
    + guide + "\nPAGE:\n" + text)
  try:
    r = gl.nondet.exec_prompt(prompt, response_format="json")
  except Exception:
    return None
  if isinstance(r, str):
    try:
      r = jl(r)
    except Exception:
      return None
  return r if isinstance(r, dict) else None


def _to_unix(date_s, clock_s, off_s):
  d = _pdate(date_s)
  c = _clock(clock_s)
  o = _poff(off_s)
  if d is None or c is None or o is None:
    return None
  return d * 86400 + c - o


def _derive_off(f, pol):
  # Delta SS4 rule (b): for a source printing bare local times, derive
  # its effective offset from its own printed scheduled arrival against
  # the committed sarr. The derived offset is snapped to the 15-minute
  # timezone grid; the derived scheduled instant must land within
  # SCHED_TOLERANCE of sarr, else the source yields no tuple from its
  # times. Returns (sched_unix, offset) or (None, None).
  d = _pdate(f.get("scheduled_date"))
  c = _clock(f.get("scheduled_arrival_local"))
  if d is None or c is None:
    return None, None
  naive = d * 86400 + c
  raw = naive - int(pol["sarr"])
  off = ((raw + 450) // 900) * 900
  if abs(raw - off) > SCHED_TOLERANCE:
    return None, None
  return naive - off, off


def _src_sched(f, pol):
  # The source's scheduled arrival as a unix instant, plus the derived
  # offset when rule (b) produced it. Rule (a): an explicit printed
  # offset wins. Then rule (b)'s derivation. Then v1's fallback: a
  # printed scheduled departure plus a printed duration.
  v = _to_unix(f.get("scheduled_date"), f.get("scheduled_arrival_local"),
               f.get("scheduled_tz_offset") or f.get("tz_offset"))
  if v is not None:
    return v, None
  v, off = _derive_off(f, pol)
  if v is not None:
    return v, off
  dep = _to_unix(f.get("sched_dep_date"), f.get("sched_dep_local"), f.get("sched_dep_tz_offset"))
  dur = f.get("duration_minutes")
  if dep is not None and isinstance(dur, (int, float)) and not isinstance(dur, bool) and dur >= 0:
    return dep + int(dur) * 60, None
  return None, None


def _arr_unix(f, pol, derived_off):
  # The source's actual arrival as a unix instant. An explicit printed
  # offset wins (rule (a)); a bare local time converts with the derived
  # offset (rule (b)). Neither v1.1 source prints an arrival date in its
  # history rows, so the date basis is the extracted arrival_date, else
  # the row's scheduled_date, else the policy's fdate; when no arrival
  # date was printed and the converted instant would precede the
  # departure instant, the arrival falls on the following day (delta SS4
  # rule (b) rollover).
  c = _clock(f.get("actual_arrival_local"))
  if c is None:
    return None
  off = _poff(f.get("tz_offset"))
  if off is None:
    off = derived_off
  if off is None:
    return None
  date_s = f.get("arrival_date") or f.get("scheduled_date") or pol["fdate"]
  d = _pdate(date_s)
  if d is None:
    return None
  v = d * 86400 + c - off
  if f.get("arrival_date") is None and v < int(pol["sdep"]):
    v += 86400
  return v


def _bucket(delay_sec: int):
  if delay_sec < 3600:
    return ("NONE", "ARRIVAL_DELAY_UNDER_60")
  if delay_sec < 10800:
    return ("PARTIAL", "ARRIVAL_DELAY_60_TO_179")
  return ("FULL", "ARRIVAL_DELAY_180_OR_MORE")


def _eval_src(f, pol):
  # One source's extracted fields -> a working record. States: down (fetch
  # or extraction failed), badid (page shows a different flight), notfound
  # (right flight, policy date absent), usable (identity + date confirmed).
  if f is None:
    return {"st": "down"}
  if f.get("identity_ok") is not True:
    return {"st": "badid"}
  if f.get("date_shown") is not True:
    return {"st": "notfound"}
  status = str(f.get("status_class", "")).strip().upper().replace(" ", "_")
  sched, derived_off = _src_sched(f, pol)
  sal = f.get("scheduled_arrival_local")
  e = {"st": "usable", "sched": sched, "tuple": None,
       "not_landed": False, "div_noarr": False,
       "sched_printed": isinstance(sal, str) and sal.strip() != "",
       "sched_derived": derived_off is not None}
  if status == "CANCELLED":
    e["tuple"] = ("FULL", "CANCELLATION", "FLIGHT_CANCELLED")
    return e
  if status in ("NOT_LANDED", "NOT_FOUND"):
    e["not_landed"] = True
    return e
  if status in ("LANDED", "DIVERTED"):
    arr = _arr_unix(f, pol, derived_off)
    tup = None
    if arr is not None:
      base = int(pol["sarr"])
      if e["sched"] is not None and e["sched"] > base:
        base = e["sched"]
      o, r = _bucket(arr - base)
      tup = (o, "DELAY", r)
    else:
      dm = f.get("delay_minutes_shown")
      if isinstance(dm, (int, float)) and not isinstance(dm, bool):
        o, r = _bucket(int(dm) * 60)
        tup = (o, "DELAY", r)
    if status == "DIVERTED" and tup is None:
      e["div_noarr"] = True
      return e
    e["tuple"] = tup
    return e
  return e


def _vnorm(d):
  # Normalize a raw verdict to the canonical dict, or None when it cannot
  # be normalized (the wrapper then raises JURY_MALFORMED).
  if not isinstance(d, dict):
    return None
  outcome = str(d.get("outcome", "")).strip().upper()
  basis = str(d.get("basis", "")).strip().upper()
  reason = str(d.get("reason_code", "")).strip().upper().replace(" ", "_")
  if outcome not in _OUTCOMES or basis not in _BASES or reason not in _REASONS:
    return None
  if _PAIRS.get((outcome, basis)) != reason:
    return None
  return {"outcome": outcome, "basis": basis, "reason_code": reason}


@gl.evm.contract_interface
class _Recipient:
  class View:
    pass

  class Write:
    pass


class FlightCover(gl.contract.Contract):
  own: str
  pown: str
  paused: str
  np: bigint
  poolf: bigint
  resw: bigint
  tcw: bigint
  tpw: bigint
  wo: bigint
  pols: TreeMap[str, str]
  obc: TreeMap[str, str]
  fxc: TreeMap[str, str]
  claimable: TreeMap[str, str]
  pendings: TreeMap[str, str]
  pstamps: TreeMap[str, str]

  def __init__(self):
    self.own = str(gl.message.sender_address).lower()
    self.pown = ""
    self.paused = "0"
    self.np = 1
    self.poolf = 0
    self.resw = 0
    self.tcw = 0
    self.tpw = 0
    self.wo = 0

  def _sender(self):
    return str(gl.message.sender_address).lower()

  def _now(self):
    try:
      return _now_unix()
    except Exception:
      raise _UE("TIME_UNAVAILABLE")

  def _noval(self):
    if int(gl.message.value) > 0:
      raise _UE("BAD_AMOUNT")

  def _load(self, policy_id):
    key = str(int(policy_id))
    if key not in self.pols:
      raise _UE("POLICY_NOT_FOUND")
    return key, jl(self.pols[key])

  def _save(self, key, pol):
    self.pols[key] = jd(pol)

  def _pot(self, addr):
    return int(self.claimable[addr]) if addr in self.claimable else 0

  def _pend(self, addr):
    return int(self.pendings[addr]) if addr in self.pendings else 0

  def _psince(self, addr):
    return int(self.pstamps[addr]) if addr in self.pstamps else 0

  def _credit(self, addr, amount):
    if amount > 0:
      self.claimable[addr] = str(self._pot(addr) + amount)
      self.tcw += amount

  def _pay(self, recipient, amount):
    if amount > 0:
      _Recipient(Address(recipient)).emit_transfer(value=u256(amount))

  def _fkey(self, pol):
    return pol["al_iata"] + ":" + pol["fno"] + ":" + pol["fdate"]

  def _dec_open(self, pol):
    buyer = pol["buyer"]
    n = int(self.obc[buyer]) if buyer in self.obc else 0
    if n <= 1:
      if buyer in self.obc:
        del self.obc[buyer]
    else:
      self.obc[buyer] = str(n - 1)
    fk = self._fkey(pol)
    left = (int(self.fxc[fk]) if fk in self.fxc else 0) - int(pol["cov"])
    if left <= 0:
      if fk in self.fxc:
        del self.fxc[fk]
    else:
      self.fxc[fk] = str(left)

  def _jury(self, pol):
    iata = pol["al_iata"]
    fno = pol["fno"]
    pm_anchor, av_anchor = _anchors(pol["fdate"])
    urls = [
      ("S1", "https://www.planemapper.com/flights/" + iata + fno, pm_anchor),
      ("S2", "https://www.avionio.com/en/flight/" + iata.lower() + "-" + fno,
       av_anchor),
    ]

    def fn():
      evals = []
      for tag, url, anchor in urls:
        text = _fetch(url)
        if text is None:
          evals.append({"st": "down"})
          continue
        evals.append(_eval_src(_extract(pol, tag, _slice(text, anchor)), pol))
      # Precedence, strict order (delta SS3); the first step that fires
      # decides. Step 1: both sources contradict the committed identity
      # (a source merely lacking the date is NOT_FOUND/unusable, never an
      # identity failure).
      if sum(1 for e in evals if e["st"] == "badid") >= 2:
        return "IDENTITY_MISMATCH"
      usable = [e for e in evals if e["st"] == "usable"]
      # Step 2: fewer than 2 usable sources, or fewer than 2 usable
      # sources yielding a valid tuple (NOT_LANDED, a diversion with no
      # printed final arrival, a landed row with no convertible arrival
      # and no printed delay). Two no-tuple sources never "agree".
      if len(usable) < 2:
        return "EVIDENCE_UNAVAILABLE"
      tuples = [e["tuple"] for e in usable]
      if sum(1 for t in tuples if t is not None) < 2:
        return "EVIDENCE_UNAVAILABLE"
      # Step 3: the two tuples disagree on the exact tuple.
      if tuples[0] != tuples[1]:
        return "EVIDENCE_UNAVAILABLE"
      agreed = tuples[0]
      # Step 4: no usable source independently corroborates the
      # committed sarr. Amendment A1: a rule-(b) derived schedule never
      # corroborates (it is computed from sarr itself). The vacuous pass
      # survives only for an agreed CANCELLATION where neither usable
      # source printed a scheduled arrival at all.
      sarr = int(pol["sarr"])
      corr = any(e["sched"] is not None and not e["sched_derived"]
                 and abs(e["sched"] - sarr) <= SCHED_TOLERANCE
                 for e in usable)
      if not corr:
        anyprinted = any(e["sched_printed"] for e in usable)
        if not (agreed[1] == "CANCELLATION" and not anyprinted):
          return "SCHEDULE_MISMATCH"
      return _cj({"outcome": agreed[0], "basis": agreed[1], "reason_code": agreed[2]})

    return str(gl.eq_principle.strict_eq(fn))

  @gl.public.write.payable
  def fund_pool(self) -> str:
    if self._sender() != self.own:
      raise _UE("NOT_ADMIN")
    v = int(gl.message.value)
    if v <= 0:
      raise _UE("BAD_AMOUNT")
    self.poolf += v
    return "OK"

  @gl.public.write.payable
  def buy_policy(self, al_iata: str, al_name: str, fno: str, dep: str, arr: str,
                 dep_city: str, arr_city: str, fdate: str, sdep: u256, sarr: u256,
                 cov: u256) -> str:
    if self.paused == "1":
      raise _UE("PAUSED")
    # Identity format (BAD_FLIGHT).
    iata = str(al_iata).upper()
    if len(iata) != 2 or not all(c.isalnum() and c.isascii() for c in iata):
      raise _UE("BAD_FLIGHT")
    name = str(al_name)
    if not (1 <= len(name) <= 40) or not _slug_ok(name):
      raise _UE("BAD_FLIGHT")
    fno = str(fno)
    if not (1 <= len(fno) <= 5) or not fno.isdigit() or int(fno) < 1 or (len(fno) > 1 and fno[0] == "0"):
      raise _UE("BAD_FLIGHT")
    dep = str(dep)
    arr = str(arr)
    if len(dep) != 3 or not all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in dep):
      raise _UE("BAD_FLIGHT")
    if len(arr) != 3 or not all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in arr):
      raise _UE("BAD_FLIGHT")
    if dep == arr:
      raise _UE("BAD_FLIGHT")
    dcity = str(dep_city)
    acity = str(arr_city)
    if not (1 <= len(dcity) <= 30) or not _slug_ok(dcity):
      raise _UE("BAD_FLIGHT")
    if not (1 <= len(acity) <= 30) or not _slug_ok(acity):
      raise _UE("BAD_FLIGHT")
    fdate = str(fdate)
    fdays = _pdate(fdate)
    if fdays is None:
      raise _UE("BAD_FLIGHT")
    # Coverage, then premium exactness.
    cov = int(cov)
    if cov < MIN_COV or cov > MAX_COV:
      raise _UE("BAD_COVERAGE")
    prem = cov * PREMIUM_BPS // 10000
    if int(gl.message.value) != prem:
      raise _UE("BAD_PREMIUM")
    # Flight times.
    now = self._now()
    sdep = int(sdep)
    sarr = int(sarr)
    if sdep <= now + MIN_LEAD:
      raise _UE("BAD_FLIGHT_TIME")
    if sarr <= sdep:
      raise _UE("BAD_FLIGHT_TIME")
    if sarr > now + MAX_HORIZON:
      raise _UE("BAD_FLIGHT_TIME")
    if not (900 <= sarr - sdep <= 86400):
      raise _UE("BAD_FLIGHT_TIME")
    if abs(sdep // 86400 - fdays) > 1:
      raise _UE("BAD_FLIGHT_TIME")
    # Buyer cap, underwriting gate, per-flight exposure cap.
    buyer = self._sender()
    ob = int(self.obc[buyer]) if buyer in self.obc else 0
    if ob >= MAX_OPEN:
      raise _UE("TOO_MANY_POLICIES")
    if self.poolf + prem - cov < 0:
      raise _UE("POOL_INSUFFICIENT")
    fk = iata + ":" + fno + ":" + fdate
    flight_after = (int(self.fxc[fk]) if fk in self.fxc else 0) + cov
    backing_after = self.poolf + prem + self.resw
    if flight_after > backing_after * FLIGHT_CAP_BPS // 10000:
      raise _UE("FLIGHT_CAP_EXCEEDED")
    pid = self.np
    self.np += 1
    self.poolf += prem - cov
    self.resw += cov
    self.fxc[fk] = str(flight_after)
    self.obc[buyer] = str(ob + 1)
    pol = {"buyer": buyer, "al_iata": iata, "al_name": name, "fno": fno,
           "dep": dep, "arr": arr, "dep_city": dcity, "arr_city": acity,
           "fdate": fdate, "sdep": str(sdep), "sarr": str(sarr),
           "cov": str(cov), "prem": str(prem), "st": "OPEN", "verdict": "",
           "basis": "", "reason": "", "payout": "0", "fails": 0,
           "first_fail_at": "0", "last_fail": "", "assessed_at": "0"}
    self.pols[str(pid)] = jd(pol)
    return str(pid)

  @gl.public.write
  def cancel_policy(self, policy_id: u256) -> str:
    self._noval()
    key, pol = self._load(policy_id)
    if pol["buyer"] != self._sender():
      raise _UE("NOT_BUYER")
    if pol["st"] != "OPEN":
      raise _UE("BAD_STATE")
    if not (self._now() < int(pol["sdep"]) - CANCEL_CUTOFF):
      raise _UE("BAD_STATE")
    cov = int(pol["cov"])
    prem = int(pol["prem"])
    self.resw -= cov
    self.poolf += cov - prem
    self._credit(pol["buyer"], prem)
    self._dec_open(pol)
    pol["st"] = "CANCELLED"
    self._save(key, pol)
    return "OK"

  @gl.public.write
  def assess_policy(self, policy_id: u256) -> str:
    self._noval()
    key, pol = self._load(policy_id)
    if pol["st"] != "OPEN":
      raise _UE("BAD_STATE")
    now = self._now()
    sarr = int(pol["sarr"])
    if now < sarr + ASSESS_OPEN_LAG:
      raise _UE("TOO_EARLY")
    if now > sarr + ASSESS_SPAN:
      raise _UE("WINDOW_CLOSED")
    agreed = self._jury(pol)
    if agreed in _TOKENS:
      pol["fails"] = int(pol["fails"]) + 1
      if pol["first_fail_at"] == "0":
        pol["first_fail_at"] = str(now)
      pol["last_fail"] = agreed
      self._save(key, pol)
      return agreed
    v = None
    if agreed.startswith("{"):
      try:
        v = _vnorm(jl(agreed))
      except Exception:
        v = None
    if v is None:
      raise _UE("JURY_MALFORMED")
    cov = int(pol["cov"])
    payout = cov * LADDER[v["outcome"]] // 10000
    self.resw -= cov
    self.poolf += cov - payout
    self._credit(pol["buyer"], payout)
    self._dec_open(pol)
    pol["st"] = _SETTLE_ST[v["outcome"]]
    pol["verdict"] = v["outcome"]
    pol["basis"] = v["basis"]
    pol["reason"] = v["reason_code"]
    pol["payout"] = str(payout)
    pol["assessed_at"] = str(now)
    self._save(key, pol)
    return _cj(v)

  @gl.public.write
  def finalize_lapsed(self, policy_id: u256) -> str:
    self._noval()
    key, pol = self._load(policy_id)
    if pol["st"] != "OPEN":
      raise _UE("BAD_STATE")
    if not (self._now() > int(pol["sarr"]) + ASSESS_SPAN):
      raise _UE("WINDOW_OPEN")
    cov = int(pol["cov"])
    self.resw -= cov
    self.poolf += cov
    self._dec_open(pol)
    pol["st"] = "LAPSED"
    self._save(key, pol)
    return "OK"

  @gl.public.write
  def claim_payout(self) -> str:
    self._noval()
    sender = self._sender()
    amt = self._pot(sender)
    if amt <= 0:
      raise _UE("NOTHING_CLAIMABLE")
    if self._pend(sender) > 0:
      raise _UE("PENDING_EXISTS")
    del self.claimable[sender]
    self.tcw -= amt
    self.pendings[sender] = str(amt)
    self.tpw += amt
    self.pstamps[sender] = str(self._now())
    self._pay(sender, amt)
    return str(amt)

  @gl.public.write
  def confirm_withdrawal(self) -> str:
    self._noval()
    sender = self._sender()
    amt = self._pend(sender)
    if amt <= 0:
      raise _UE("NO_PENDING")
    del self.pendings[sender]
    self.tpw -= amt
    if sender in self.pstamps:
      del self.pstamps[sender]
    return "OK"

  @gl.public.write
  def restore_pending(self) -> str:
    self._noval()
    sender = self._sender()
    amt = self._pend(sender)
    if amt <= 0:
      raise _UE("NO_PENDING")
    if self._now() - self._psince(sender) < RESTORE_DELAY:
      raise _UE("PENDING_TOO_YOUNG")
    if int(self.balance) < self.poolf + self.resw + self.tcw + self.tpw:
      raise _UE("INSUFFICIENT_BACKING")
    del self.pendings[sender]
    self.tpw -= amt
    if sender in self.pstamps:
      del self.pstamps[sender]
    self._credit(sender, amt)
    return "OK"

  @gl.public.write
  def write_off_pending(self, payee: str) -> str:
    self._noval()
    payee = str(payee).lower()
    amt = self._pend(payee)
    if amt <= 0:
      raise _UE("NO_PENDING")
    sender = self._sender()
    if sender != payee and sender != self.own:
      raise _UE("NOT_PAYEE")
    if self._now() - self._psince(payee) < WRITEOFF_DELAY:
      raise _UE("PENDING_TOO_YOUNG")
    if not (int(self.balance) < self.poolf + self.resw + self.tcw + self.tpw):
      raise _UE("NO_SHORTFALL")
    del self.pendings[payee]
    self.tpw -= amt
    if payee in self.pstamps:
      del self.pstamps[payee]
    self.wo += amt
    return "OK"

  @gl.public.write
  def withdraw_pool(self, amount: u256) -> str:
    self._noval()
    if self._sender() != self.own:
      raise _UE("NOT_ADMIN")
    amount = int(amount)
    if amount <= 0:
      raise _UE("BAD_AMOUNT")
    if amount > self.poolf:
      raise _UE("POOL_INSUFFICIENT")
    if int(self.balance) - amount < self.resw + self.tcw:
      raise _UE("INSUFFICIENT_BACKING")
    self.poolf -= amount
    self._credit(self.own, amount)
    return "OK"

  @gl.public.write
  def set_paused(self, flag: bool) -> str:
    self._noval()
    if self._sender() != self.own:
      raise _UE("NOT_ADMIN")
    self.paused = "1" if flag else "0"
    return "OK"

  @gl.public.write
  def transfer_ownership(self, new_owner: str) -> str:
    self._noval()
    if self._sender() != self.own:
      raise _UE("NOT_ADMIN")
    a = str(new_owner).strip().lower()
    if not _valid_addr(a) or a == self.own:
      raise _UE("BAD_ADDRESS")
    self.pown = a
    return "OK"

  @gl.public.write
  def accept_ownership(self) -> str:
    self._noval()
    if not self.pown or self._sender() != self.pown:
      raise _UE("NO_PENDING_ADMIN")
    self.own = self.pown
    self.pown = ""
    return "OK"

  @gl.public.view
  def get_policy(self, policy_id: u256) -> str:
    key, pol = self._load(policy_id)
    return jd(pol)

  @gl.public.view
  def get_overview(self) -> str:
    return jd({"owner": self.own, "paused": self.paused == "1",
               "npolicies": str(int(self.np) - 1), "poolf": str(self.poolf),
               "resw": str(self.resw), "tcw": str(self.tcw),
               "tpw": str(self.tpw), "written_off": str(self.wo),
               "contract_balance_wei": str(int(self.balance))})

  @gl.public.view
  def get_claimable(self, address: str) -> str:
    return str(self._pot(str(address).lower()))

  @gl.public.view
  def get_pending(self, address: str) -> str:
    a = str(address).lower()
    return jd({"amt": str(self._pend(a)), "since": str(self._psince(a))})
