"""Cloudflare Access identity-token verification for the decision board.

The board is reached behind Cloudflare Access and verifies the Access JWT
itself (ruling R2, issue #6). `AccessJwtVerifier.verify` takes the raw token
and answers `Verified(email)` or `Rejected(reason)`; reading the request
header and building the verifier from configuration belong to the server
wiring.

The token is parsed strictly by this module before PyJWT sees it: bounded
length and nesting, no duplicate JSON members, an RS256-only header naming its
key by `kid`, and no header member that would let the token choose its own
key. PyJWT then verifies the signature, audience and issuer; the time claims
are checked here against the injected wall clock, so leeway has one owner.

Signing keys come from the team's own certs URL through the injected fetch.
A fetched key set replaces the cached one only once every key in it is a
valid public RSA signing key, so a failed or poisoned refresh never evicts
the last good set; that set expires on the injected monotonic clock.
"""

from __future__ import annotations

import base64
import contextlib
import http.client
import json
import math
import queue
import re
import socket
import ssl
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from types import MappingProxyType
from typing import NoReturn, TypeGuard

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey, RSAPublicNumbers
from jwt.types import Options

LEEWAY_SECONDS = 60
MAX_TOKEN_CHARACTERS = 8 * 1024
MAX_JSON_NESTING_DEPTH = 8
MAX_KEY_ID_CHARACTERS = 128
KEY_SET_TTL_SECONDS = 60 * 60
KEY_SET_REFRESH_COOLDOWN_SECONDS = 30
KEY_SET_FETCH_TIMEOUT_SECONDS = 5
MAX_KEY_SET_BYTES = 64 * 1024
MAX_KEY_SET_KEYS = 10
MIN_RSA_KEY_BITS = 2048

_ALGORITHM = "RS256"
_JWS_COMPACT_SEGMENTS = 3
_TEAM_NAME = re.compile(r"[a-z0-9-]{1,63}")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]*")
# Members through which a token could name, embed or constrain its own key,
# and `b64`, which would change how PyJWT reads the payload segment.
_FORBIDDEN_HEADER_MEMBERS = frozenset({"crit", "jwk", "jku", "x5u", "x5c", "b64"})
_PRIVATE_RSA_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth"})

WallClock = Callable[[], float]
"""Seconds since the epoch, compared with the token's `exp`, `iat` and `nbf`."""
MonotonicClock = Callable[[], float]
"""Seconds on a clock that never jumps; ages the key set and its cooldown."""
KeySetFetch = Callable[[str], bytes]
"""Fetches the key set document at the URL, raising `KeySetFetchError` on failure."""


class RejectionReason(StrEnum):
    TOKEN_TOO_LONG = "token-too-long"
    MALFORMED_TOKEN = "malformed-token"
    DUPLICATE_MEMBER = "duplicate-member"
    NESTING_TOO_DEEP = "nesting-too-deep"
    FORBIDDEN_HEADER = "forbidden-header"
    UNSUPPORTED_ALGORITHM = "unsupported-algorithm"
    INVALID_KEY_ID = "invalid-key-id"
    UNKNOWN_KEY_ID = "unknown-key-id"
    KEY_SET_UNAVAILABLE = "key-set-unavailable"
    INVALID_SIGNATURE = "invalid-signature"
    INVALID_AUDIENCE = "invalid-audience"
    INVALID_ISSUER = "invalid-issuer"
    INVALID_CLAIM = "invalid-claim"
    SERVICE_TOKEN = "service-token"
    WRONG_TOKEN_TYPE = "wrong-token-type"
    EXPIRED = "expired"
    ISSUED_IN_FUTURE = "issued-in-future"
    NOT_YET_VALID = "not-yet-valid"


@dataclass(frozen=True)
class Verified:
    email: str


@dataclass(frozen=True)
class Rejected:
    reason: RejectionReason


class KeySetFetchError(Exception):
    """The key set could not be fetched: refused, timed out, redirected, or broken off."""


class _RefusalError(Exception):
    def __init__(self, reason: RejectionReason) -> None:
        super().__init__(reason)
        self.reason = reason


class _InvalidKeySetError(Exception):
    """A fetched key set that must not replace the cached one."""


@dataclass(frozen=True)
class _ParsedToken:
    key_id: str
    claims: Mapping[str, object]


@dataclass(frozen=True)
class _KeySet:
    keys: Mapping[str, RSAPublicKey]
    fetched_at: float


class AccessJwtVerifier:
    """Verifies Cloudflare Access identity tokens for one team and one application.

    Safe to share between the server's request threads: the cached key set is
    an immutable snapshot swapped in whole, and one refresh runs at a time.
    """

    def __init__(
        self,
        *,
        team: str,
        audience: str,
        fetch_key_set: KeySetFetch,
        wall_clock: WallClock,
        monotonic_clock: MonotonicClock,
    ) -> None:
        if not _TEAM_NAME.fullmatch(team):
            raise ValueError(f"Cloudflare Access team name {team!r} is not [a-z0-9-]{{1,63}}")
        if not audience:
            raise ValueError("Cloudflare Access audience tag must not be empty")
        self._issuer = f"https://{team}.cloudflareaccess.com"
        self._key_set_url = f"{self._issuer}/cdn-cgi/access/certs"
        self._audience = audience
        self._fetch_key_set = fetch_key_set
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._key_set: _KeySet | None = None
        self._last_refresh_at: float | None = None
        self._refresh_lock = threading.Lock()

    def verify(self, token: str) -> Verified | Rejected:
        try:
            return Verified(self._verified_email(token))
        except _RefusalError as refusal:
            return Rejected(refusal.reason)

    def _verified_email(self, token: str) -> str:
        parsed = _parse_token(token)
        self._verify_signature_audience_and_issuer(token, self._signing_key(parsed.key_id))
        return self._identity_email(parsed.claims)

    def _verify_signature_audience_and_issuer(self, token: str, key: RSAPublicKey) -> None:
        try:
            jwt.decode(
                token,
                key=key,
                algorithms=[_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options=_library_checks(),
            )
        except jwt.InvalidSignatureError as error:
            raise _RefusalError(RejectionReason.INVALID_SIGNATURE) from error
        # After InvalidSignatureError, which subclasses it. `_parse_token`
        # already refuses what PyJWT cannot decode; this keeps a disagreement
        # between the two parses a rejection rather than an exception.
        except jwt.DecodeError as error:
            raise _RefusalError(RejectionReason.MALFORMED_TOKEN) from error
        except jwt.InvalidAudienceError as error:
            raise _RefusalError(RejectionReason.INVALID_AUDIENCE) from error
        except jwt.InvalidIssuerError as error:
            raise _RefusalError(RejectionReason.INVALID_ISSUER) from error
        except jwt.MissingRequiredClaimError as error:
            raise _RefusalError(RejectionReason.INVALID_CLAIM) from error

    def _identity_email(self, claims: Mapping[str, object]) -> str:
        if "common_name" in claims or "email" not in claims:
            raise _RefusalError(RejectionReason.SERVICE_TOKEN)
        email = claims["email"]
        if not isinstance(email, str) or not email:
            raise _RefusalError(RejectionReason.INVALID_CLAIM)
        if claims.get("type") != "app":
            raise _RefusalError(RejectionReason.WRONG_TOKEN_TYPE)
        self._check_time_claims(claims)
        return email

    def _check_time_claims(self, claims: Mapping[str, object]) -> None:
        expires_at = _integer_claim(claims, "exp")
        issued_at = _integer_claim(claims, "iat")
        not_before = _integer_claim(claims, "nbf") if "nbf" in claims else None
        now = self._wall_clock()
        if now >= expires_at + LEEWAY_SECONDS:
            raise _RefusalError(RejectionReason.EXPIRED)
        if issued_at > now + LEEWAY_SECONDS:
            raise _RefusalError(RejectionReason.ISSUED_IN_FUTURE)
        if not_before is not None and not_before > now + LEEWAY_SECONDS:
            raise _RefusalError(RejectionReason.NOT_YET_VALID)

    def _signing_key(self, key_id: str) -> RSAPublicKey:
        key_set = self._key_set
        if not self._is_current(key_set) or key_id not in key_set.keys:
            self._refresh_key_set()
            key_set = self._key_set
        if not self._is_current(key_set):
            raise _RefusalError(RejectionReason.KEY_SET_UNAVAILABLE)
        key = key_set.keys.get(key_id)
        if key is None:
            raise _RefusalError(RejectionReason.UNKNOWN_KEY_ID)
        return key

    def _is_current(self, key_set: _KeySet | None) -> TypeGuard[_KeySet]:
        return (
            key_set is not None
            and self._monotonic_clock() - key_set.fetched_at < KEY_SET_TTL_SECONDS
        )

    def _refresh_key_set(self) -> None:
        # A request arriving while another refreshes does not wait for it: it
        # fails closed on the snapshot it already holds, so a flood of unknown
        # `kid`s costs one fetch and no blocked server threads.
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            now = self._monotonic_clock()
            if (
                self._last_refresh_at is not None
                and now - self._last_refresh_at < KEY_SET_REFRESH_COOLDOWN_SECONDS
            ):
                return
            self._last_refresh_at = now
            try:
                keys = _parse_key_set(self._fetch_key_set(self._key_set_url))
            except (KeySetFetchError, _InvalidKeySetError):
                return
            self._key_set = _KeySet(keys=keys, fetched_at=now)
        finally:
            self._refresh_lock.release()


def fetch_key_set_over_https(
    url: str, *, deadline_seconds: float = KEY_SET_FETCH_TIMEOUT_SECONDS
) -> bytes:
    """The production `KeySetFetch`: HTTPS only, no redirect followed, no proxy
    from the environment, the wait for name resolution, connecting and the
    exchange all held to one deadline, and at most one byte past the key-set
    limit read, so the verifier refuses an oversized answer without buffering
    it."""
    deadline = time.monotonic() + deadline_seconds
    origin = urllib.parse.urlsplit(url)
    host = origin.hostname
    if origin.scheme != "https" or not host:
        raise KeySetFetchError(f"refusing to fetch the key set from {url}: not an https URL")
    port = origin.port or http.client.HTTPS_PORT
    try:
        with (
            _connect_before(deadline, host, port) as connection,
            _cut_off_at(deadline, connection),
        ):
            return _get_over_tls(connection, host, port, origin.path or "/")
    except (OSError, http.client.HTTPException) as error:
        raise KeySetFetchError(f"fetching the key set from {url} failed: {error}") from error


def _connect_before(deadline: float, host: str, port: int) -> socket.socket:
    """Resolves `host` and connects to the first of its addresses that
    answers, all before `deadline`. `socket.create_connection` would resolve
    without any timeout and give every address the whole one."""
    addresses = _SYSTEM_NAME_RESOLVER.addresses(host, port, deadline)
    failure = OSError(f"{host} resolved to no address")
    for family, kind, protocol, _canonical_name, address in addresses:
        time_left = _time_left_before(deadline)
        connection = None
        try:
            connection = socket.socket(family, kind, protocol)
            connection.settimeout(time_left)
            connection.connect(address)
        except OSError as error:
            if connection is not None:
                connection.close()
            failure = error
        else:
            return connection
    raise failure


_AddressInfo = tuple[
    socket.AddressFamily,
    socket.SocketKind,
    int,
    str,
    tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes],
]


# A verifier fetches single-flight, so a second lookup waiting behind the one
# in progress means the resolver is stalled.
_WAITING_NAME_LOOKUPS_LIMIT = 1


class _NameResolver:
    """Resolves names on one daemon thread for the whole process.

    `getaddrinfo` takes no timeout and cannot be interrupted, so a caller can
    only stop waiting for it, and only the system resolver ends a lookup. One
    thread for every lookup and a bounded line of lookups waiting for it bound
    what a stalled resolver holds: a lookup that finds the line full is refused
    at once, a lookup whose caller gave up before it started is skipped, and as
    a daemon the thread never holds the interpreter's exit."""

    def __init__(self) -> None:
        self._lookups: queue.Queue[tuple[Future[list[_AddressInfo]], str, int]] = queue.Queue(
            maxsize=_WAITING_NAME_LOOKUPS_LIMIT
        )
        self._worker_start = threading.Lock()
        self._worker: threading.Thread | None = None

    def addresses(self, host: str, port: int, deadline: float) -> list[_AddressInfo]:
        time_left = _time_left_before(deadline)
        lookup: Future[list[_AddressInfo]] = Future()
        self._start_worker_once()
        try:
            self._lookups.put_nowait((lookup, host, port))
        except queue.Full as error:
            raise KeySetFetchError(f"name resolution for {host} is stalled") from error
        try:
            return lookup.result(timeout=time_left)
        except TimeoutError as error:
            lookup.cancel()
            raise _deadline_passed() from error

    def _start_worker_once(self) -> None:
        with self._worker_start:
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._resolve_forever, name="key-set-name-resolver", daemon=True
                )
                self._worker.start()

    def _resolve_forever(self) -> NoReturn:
        while True:
            lookup, host, port = self._lookups.get()
            if not lookup.set_running_or_notify_cancel():
                continue
            # Handed to the waiting caller, which raises it as its own.
            try:
                lookup.set_result(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except Exception as error:
                lookup.set_exception(error)


_SYSTEM_NAME_RESOLVER = _NameResolver()


def _time_left_before(deadline: float) -> float:
    time_left = deadline - time.monotonic()
    if time_left <= 0:
        raise _deadline_passed()
    return time_left


def _deadline_passed() -> KeySetFetchError:
    return KeySetFetchError("the key set fetch passed its deadline")


def _get_over_tls(connection: socket.socket, host: str, port: int, path: str) -> bytes:
    tls = _certificate_verifying_tls()
    # Handed the connection ready-made, so `_cut_off_at` holds it from the
    # first TLS byte; `http.client` follows no redirect and reads no proxy.
    exchange = http.client.HTTPSConnection(host, port, context=tls)
    try:
        exchange.sock = tls.wrap_socket(connection, server_hostname=host)
        exchange.request("GET", path)
        with exchange.getresponse() as response:
            if response.status != HTTPStatus.OK:
                raise KeySetFetchError(f"the key set origin answered {response.status}, not 200")
            return response.read(MAX_KEY_SET_BYTES + 1)
    finally:
        exchange.close()


@contextlib.contextmanager
def _cut_off_at(deadline: float, connection: socket.socket) -> Iterator[None]:
    """Shuts `connection` down at `deadline`, wherever the exchange stands.
    The socket timeout bounds each read alone, so without this a peer sending
    a byte just inside it would hold the refresh, and its lock, indefinitely."""
    # A duplicate descriptor stays usable after TLS takes `connection` over,
    # and shutting it down ends the one connection both name.
    watched = connection.dup()
    cut_off = threading.Event()

    def shut_down() -> None:
        cut_off.set()
        # A connection the peer already broke needs no cutting.
        with contextlib.suppress(OSError):
            watched.shutdown(socket.SHUT_RDWR)

    timer = threading.Timer(deadline - time.monotonic(), shut_down)
    timer.daemon = True
    timer.start()
    try:
        yield
    except (OSError, http.client.HTTPException):
        # Wherever the cut lands, the exchange fails with what it was doing
        # then; the deadline is the cause worth reporting.
        if not cut_off.is_set():
            raise
    finally:
        timer.cancel()
        timer.join()
        watched.close()
    # Reached after a cut too: a body cut short may just read short.
    if cut_off.is_set():
        raise _deadline_passed()


def _certificate_verifying_tls() -> ssl.SSLContext:
    """The system's trusted certificates, a verified chain and a matching host
    name. The default context already requires both; they are stated so the
    one thing this key-set origin is trusted for stays visible here."""
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _library_checks() -> Options:
    """PyJWT's options, built fresh for every call so no caller can alter a
    shared one. Time claims are off here because `_check_time_claims` owns
    them; `sub` and `jti` are not part of the Access identity profile."""
    return {
        "verify_signature": True,
        "verify_aud": True,
        "verify_iss": True,
        "verify_exp": False,
        "verify_iat": False,
        "verify_nbf": False,
        "verify_sub": False,
        "verify_jti": False,
    }


def _parse_token(token: str) -> _ParsedToken:
    if len(token) > MAX_TOKEN_CHARACTERS:
        raise _RefusalError(RejectionReason.TOKEN_TOO_LONG)
    segments = token.split(".")
    if len(segments) != _JWS_COMPACT_SEGMENTS:
        raise _RefusalError(RejectionReason.MALFORMED_TOKEN)
    try:
        header_bytes, claims_bytes, _signature = (_base64url_decode(part) for part in segments)
    except ValueError as error:
        raise _RefusalError(RejectionReason.MALFORMED_TOKEN) from error
    header = _strict_json_object(header_bytes)
    claims = _strict_json_object(claims_bytes)
    return _ParsedToken(key_id=_header_key_id(header), claims=claims)


def _header_key_id(header: Mapping[str, object]) -> str:
    if _FORBIDDEN_HEADER_MEMBERS & header.keys():
        raise _RefusalError(RejectionReason.FORBIDDEN_HEADER)
    if header.get("alg") != _ALGORITHM:
        raise _RefusalError(RejectionReason.UNSUPPORTED_ALGORITHM)
    key_id = header.get("kid")
    if not _is_key_id(key_id):
        raise _RefusalError(RejectionReason.INVALID_KEY_ID)
    return key_id


def _is_key_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and 0 < len(value) <= MAX_KEY_ID_CHARACTERS


def _integer_claim(claims: Mapping[str, object], name: str) -> int:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _RefusalError(RejectionReason.INVALID_CLAIM)
    return value


def _base64url_decode(segment: str) -> bytes:
    """Decodes unpadded base64url, refusing what the lenient stdlib decoder
    would silently skip or round off, so this parse accepts exactly the
    canonical segments PyJWT accepts and both read the same bytes."""
    if not _BASE64URL.fullmatch(segment):
        raise ValueError("not base64url")
    decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    if base64.urlsafe_b64encode(decoded).rstrip(b"=") != segment.encode():
        raise ValueError("not canonical base64url")
    return decoded


def _strict_json_object(document: bytes) -> dict[str, object]:
    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _RefusalError(RejectionReason.MALFORMED_TOKEN) from error
    # Measured before parsing: the stdlib parser recurses per level and would
    # raise RecursionError on hostile nesting rather than a parse error.
    if _nesting_depth(text) > MAX_JSON_NESTING_DEPTH:
        raise _RefusalError(RejectionReason.NESTING_TOO_DEEP)
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_refuse_non_json_constant,
            parse_float=_finite_number,
        )
    except ValueError as error:
        raise _RefusalError(RejectionReason.MALFORMED_TOKEN) from error
    if not isinstance(parsed, dict):
        raise _RefusalError(RejectionReason.MALFORMED_TOKEN)
    return parsed


def _nesting_depth(text: str) -> int:
    depth = deepest = 0
    in_string = escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif character in "]}":
            depth -= 1
    return deepest


def _object_without_duplicates(members: list[tuple[str, object]]) -> dict[str, object]:
    parsed = dict(members)
    if len(parsed) != len(members):
        raise _RefusalError(RejectionReason.DUPLICATE_MEMBER)
    return parsed


def _refuse_non_json_constant(constant: str) -> NoReturn:
    """The stdlib parser reads `NaN`, `Infinity` and `-Infinity`; JSON has none."""
    raise ValueError(f"{constant} is not JSON")


def _finite_number(literal: str) -> float:
    """A literal such as `1e999999` is valid JSON that `float` rounds to an
    infinity, the value `_refuse_non_json_constant` keeps out."""
    number = float(literal)
    if not math.isfinite(number):
        raise ValueError(f"{literal} overflows to a non-finite number")
    return number


def _parse_key_set(document: bytes) -> Mapping[str, RSAPublicKey]:
    if len(document) > MAX_KEY_SET_BYTES:
        raise _InvalidKeySetError("key set response is too large")
    try:
        parsed = _strict_json_object(document)
    except _RefusalError as refusal:
        raise _InvalidKeySetError(f"key set is not strict JSON: {refusal.reason}") from None
    jwks = parsed.get("keys")
    if not isinstance(jwks, list) or not 0 < len(jwks) <= MAX_KEY_SET_KEYS:
        raise _InvalidKeySetError("key set must hold between one and the maximum of keys")
    keys: dict[str, RSAPublicKey] = {}
    for jwk in jwks:
        key_id, key = _public_signing_key(jwk)
        if key_id in keys:
            raise _InvalidKeySetError(f"key set repeats kid {key_id!r}")
        keys[key_id] = key
    return MappingProxyType(keys)


def _public_signing_key(jwk: object) -> tuple[str, RSAPublicKey]:
    if not isinstance(jwk, dict):
        raise _InvalidKeySetError("key is not an object")
    if jwk.get("kty") != "RSA" or _PRIVATE_RSA_MEMBERS & jwk.keys():
        raise _InvalidKeySetError("key is not a public RSA key")
    if not _is_rs256_verification_key(jwk):
        raise _InvalidKeySetError("key is not an RS256 signing key")
    key_id = jwk.get("kid")
    modulus, exponent = jwk.get("n"), jwk.get("e")
    if not _is_key_id(key_id) or not isinstance(modulus, str) or not isinstance(exponent, str):
        raise _InvalidKeySetError("key lacks a valid kid, n or e")
    try:
        key = RSAPublicNumbers(
            e=_base64url_unsigned(exponent), n=_base64url_unsigned(modulus)
        ).public_key()
    except ValueError as error:
        raise _InvalidKeySetError(f"key {key_id!r} is not a valid RSA key") from error
    if key.key_size < MIN_RSA_KEY_BITS:
        raise _InvalidKeySetError(f"key {key_id!r} is shorter than {MIN_RSA_KEY_BITS} bits")
    return key_id, key


def _is_rs256_verification_key(jwk: Mapping[str, object]) -> bool:
    """A key may limit itself by `alg`, `use` and `key_ops`; each it names
    must allow verifying an RS256 signature."""
    key_operations = jwk.get("key_ops", ["verify"])
    return (
        jwk.get("alg", _ALGORITHM) == _ALGORITHM
        and jwk.get("use", "sig") == "sig"
        and isinstance(key_operations, list)
        and "verify" in key_operations
    )


def _base64url_unsigned(value: str) -> int:
    return int.from_bytes(_base64url_decode(value), byteorder="big")
