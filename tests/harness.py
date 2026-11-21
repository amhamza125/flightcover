"""Offline harness: stub genlayer runtime, load FlightCover.v1.1.py, drive it.

Mirrors ~/workspace/heirloom/tests-v2/harness.py. The jury is stubbed at
two levels: WEB maps URL -> (status, body bytes) (a missing key raises,
like an unreachable host), and PROMPT_FN returns the per-source extracted
field dicts the LLM would produce — the harness keys it by the source tag
(S1/S2) found in the prompt, so the contract's own fetch, slicing,
extraction plumbing, deterministic math and precedence all run for real.
Every URL the contract requests is recorded in URLS (template tests).
"""
import sys, os, types, json

TRANSFERS = []          # (recipient, amount) emitted via _Recipient.emit_transfer
WEB = {}                # url -> (status, bytes); missing key = fetch failure
URLS = []               # every URL requested through the web stub, in order
PROMPT_FN = None        # callable(prompt, images) -> dict (extraction stub)
EQ_FN = None            # optional override for strict_eq (malformed-verdict tests)
CLOCK = {"iso": "2026-11-16T00:00:00"}

class UserError(Exception):
    pass

class _Msg:
    sender_address = "0x" + "a" * 40
    value = 0
    @property
    def datetime(self):
        return CLOCK["iso"]

class _Resp:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

class _Web:
    @staticmethod
    def get(url):
        URLS.append(url)
        if url not in WEB:
            raise Exception("unreachable: " + str(url))
        status, body = WEB[url]
        return _Resp(body, status)

class _Nondet:
    web = _Web()
    @staticmethod
    def exec_prompt(prompt, response_format=None, images=None):
        assert PROMPT_FN is not None, "no jury stub set"
        return PROMPT_FN(prompt, images)

class _Eq:
    @staticmethod
    def strict_eq(fn):
        if EQ_FN is not None:
            return EQ_FN(fn)
        return fn()

class _Public:
    def write(self, fn):
        return fn
    write.payable = staticmethod(lambda fn: fn)
    def view(self, fn):
        return fn

class _Recipient:
    def __init__(self, addr):
        self.addr = str(addr)
    def emit_transfer(self, value=None):
        TRANSFERS.append((self.addr, int(value)))

def _contract_interface(cls):
    return _Recipient

class _Contract:
    balance = 0

gl = types.ModuleType("genlayer")
gl.contract = types.SimpleNamespace(Contract=_Contract)
gl.public = _Public()
gl.vm = types.SimpleNamespace(UserError=UserError)
gl.message = _Msg()
gl.nondet = _Nondet()
gl.eq_principle = _Eq()
gl.evm = types.SimpleNamespace(contract_interface=_contract_interface)
storage = types.ModuleType("genlayer.storage")

class GenerationError(Exception):
    """Stub of genlayer.storage._internal.generate.GenerationError."""

# GenVM rule this stub now enforces: generic storage classes (TreeMap, ...)
# may only be allocated through the class-annotation machinery
# (gl.storage.inmem_allocate) — never by calling TreeMap() directly, e.g.
# inside a contract's __init__. The real VM rejects such code at deploy
# time with GenerationError (FlightCover's first Bradbury deploy died
# exactly this way: MAJORITY_AGREE but FINISHED_WITH_ERROR), while a plain
# dict-subclass stub silently accepts it. NOTE: the Heirloom harness this
# file mirrors has the same permissive stub and does NOT model the rule —
# Heirloom was protected only by its source never calling TreeMap() in
# __init__. Here, direct construction raises; only fresh()'s allocation
# step (playing the inmem_allocate role for the annotated fields) and the
# inmem_allocate stub below may create instances.
_ALLOCATING = {"on": False}

class TreeMap(dict):
    def __init__(self, *args, **kwargs):
        if not _ALLOCATING["on"]:
            raise GenerationError(
                "generic storage classes can not be instantiated with "
                "__init__, please, use gl.storage.inmem_allocate")
        super().__init__(*args, **kwargs)

def _inmem_allocate(cls, *args, **kwargs):
    _ALLOCATING["on"] = True
    try:
        return cls(*args, **kwargs)
    finally:
        _ALLOCATING["on"] = False

storage.TreeMap = TreeMap
storage.GenerationError = GenerationError
storage.inmem_allocate = _inmem_allocate
gtypes = types.ModuleType("genlayer.types")
gtypes.Address = lambda a: str(a)
gtypes.u256 = int
gtypes.bigint = int
sys.modules["genlayer"] = gl
sys.modules["genlayer.storage"] = storage
sys.modules["genlayer.types"] = gtypes

SRC_PATH = os.environ.get("FC_SRC", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "FlightCover.py"))
SRC = open(SRC_PATH).read()
ns = {}
exec(compile(SRC, SRC_PATH, "exec"), ns)
FlightCover = ns["FlightCover"]

A = "0xd2af69bb67d446526661a80a280820599c601ed3"   # admin (deployer)
B = "0x0bba411375d7074178980e610b5311dd6ed34d74"   # buyer 1
C = "0x6fa23bd191266a8680c195e6a618d2d9d584cab"   # buyer 2 / outsider
D = "0x" + "d" * 40                                # buyer 3
E = "0x" + "e" * 40                                # buyer 4
ZERO = "0x" + "0" * 40
DAY = 86400

def set_time(unix):
    import datetime as _dt
    CLOCK["iso"] = _dt.datetime.utcfromtimestamp(unix).strftime("%Y-%m-%dT%H:%M:%S")

def now_unix():
    import calendar as _cal
    s = CLOCK["iso"]
    return _cal.timegm((int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19])))

_MAPS = ("pols", "obc", "fxc", "claimable", "pendings", "pstamps")
_SCALARS = ("own", "pown", "paused", "np", "poolf", "resw", "tcw", "tpw", "wo")

def fresh(balance=0):
    TRANSFERS.clear()
    URLS.clear()
    gl.message.sender_address = A
    c = FlightCover.__new__(FlightCover)
    # Play the GenVM's annotation-allocation role (inmem_allocate) for the
    # class-level TreeMap fields; a direct TreeMap() anywhere else — in
    # particular inside the contract's __init__ — raises GenerationError.
    _ALLOCATING["on"] = True
    try:
        for m in _MAPS:
            setattr(c, m, TreeMap())
    finally:
        _ALLOCATING["on"] = False
    FlightCover.__init__(c)
    c.balance = balance
    return c

def call(c, sender, fn, *args, value=0):
    """Run one top-level call the way the chain would: value lands first,
    transfers emitted during the call leave the contract balance."""
    gl.message.sender_address = sender
    gl.message.value = value
    if value:
        c.balance += value
    before = len(TRANSFERS)
    try:
        out = fn(*args)
    finally:
        for (_r, amt) in TRANSFERS[before:]:
            c.balance -= amt
    return out

def _snap(c):
    parts = [json.dumps({k: v for k, v in getattr(c, m).items()}, sort_keys=True) for m in _MAPS]
    parts += [str(getattr(c, s)) for s in _SCALARS]
    parts.append(str(len(TRANSFERS)))
    return tuple(parts)

def expect_err(c, sender, fn, *args, code, value=0):
    """Assert the exact error, unchanged stored state, and zero fund
    movement. NOTE: harness cannot roll back in-place edits on raise; the
    contract only mutates after all gates pass, so snapshots must match.
    For payable calls the sent value stays in the balance (the GenVM
    stray) — use stray() for those."""
    snap = _snap(c)
    bal = int(c.balance)
    try:
        call(c, sender, fn, *args, value=value)
    except UserError as e:
        assert str(e) == code, f"expected {code}, got {e}"
        assert _snap(c) == snap, f"state changed on {code}"
        if value:
            assert int(c.balance) == bal + value, "payable stray missing"
            c.balance = bal   # account the stray away for the next step
        else:
            assert int(c.balance) == bal, f"balance moved on {code}"
        return
    raise AssertionError(f"expected UserError {code}, call succeeded")

def stray(c, sender, fn, *args, code, value):
    """A rejected payable call: exact error, storage/counters/TRANSFERS
    byte-identical, and the sent value visible as balance above the
    accounted total (SPEC §9 payable-residual caveat). Restores the
    pre-call balance afterwards so scenarios stay composable."""
    expect_err(c, sender, fn, *args, code=code, value=value)

def conserve(c, dust=0):
    excess = int(c.balance) - int(c.poolf) - int(c.resw) - int(c.tcw) - int(c.tpw)
    assert excess == dust, f"conservation broken: excess={excess} expected dust={dust} " \
        f"(bal={c.balance} poolf={c.poolf} resw={c.resw} tcw={c.tcw} tpw={c.tpw})"
    assert excess >= 0

def acct(c):
    return int(c.poolf) + int(c.resw) + int(c.tcw) + int(c.tpw)
