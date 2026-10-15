"""Cloudflare Access identity-token verification (issue #25).

Every scenario drives `AccessJwtVerifier.verify` with a raw token string, the
way the board's server will (AC2). The key-set endpoint and both clocks are
fakes, so the verifier's own refusals, cache and refresh rules are observed
offline and deterministically; only `fetch_key_set_over_https`, the real
HTTPS boundary, is driven against a loopback TLS server.
"""

from __future__ import annotations

import base64
import contextlib
import datetime
import hashlib
import hmac
import ipaddress
import json
import ssl
import string
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, NoReturn

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from jwt.algorithms import RSAAlgorithm

from aco_board.access_jwt import (
    KEY_SET_REFRESH_COOLDOWN_SECONDS,
    KEY_SET_TTL_SECONDS,
    LEEWAY_SECONDS,
    MAX_JSON_NESTING_DEPTH,
    MAX_KEY_ID_CHARACTERS,
    MAX_KEY_SET_BYTES,
    MAX_KEY_SET_KEYS,
    MAX_TOKEN_CHARACTERS,
    AccessJwtVerifier,
    KeySetFetchError,
    Rejected,
    RejectionReason,
    Verified,
    fetch_key_set_over_https,
)

_ABSENT = object()
"""A claim or header change that removes the member instead of setting it."""


@cache
def _rsa_key(name: str, bits: int = 2048) -> rsa.RSAPrivateKey:
    """One generated key per name for the whole module: RSA generation is the
    slow part, and a key is immutable scenario data."""
    del name
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def _segment(value: dict[str, Any] | str) -> str:
    """A base64url segment of a JSON object, or of raw JSON text when the
    scenario needs bytes `json.dumps` cannot produce (duplicate members)."""
    text = value if isinstance(value, str) else json.dumps(value)
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


def _rs256(key: rsa.RSAPrivateKey) -> Callable[[bytes], bytes]:
    return lambda signing_input: key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())


def _hs256_with_public_key(key: rsa.RSAPrivateKey) -> Callable[[bytes], bytes]:
    """The RS/HS confusion attack: HMAC keyed with the published public key."""
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return lambda signing_input: hmac.new(public_pem, signing_input, hashlib.sha256).digest()


def _jws(header: dict[str, Any] | str, claims: dict[str, Any] | str, sign: Callable) -> str:
    signing_input = f"{_segment(header)}.{_segment(claims)}"
    signature = base64.urlsafe_b64encode(sign(signing_input.encode())).rstrip(b"=").decode()
    return f"{signing_input}.{signature}"


_BASE64URL_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"


def _with_unused_signature_bits_set(token: str) -> str:
    """The same signature bytes spelled non-canonically. The last character
    of a 256-byte signature carries two signature bits and four unused zero
    bits, so the next alphabet character only sets an unused bit."""
    last = token[-1]
    return token[:-1] + _BASE64URL_ALPHABET[_BASE64URL_ALPHABET.index(last) + 1]


def _changed(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    merged = {**base, **changes}
    return {name: value for name, value in merged.items() if value is not _ABSENT}


def _public_jwk(key: rsa.RSAPrivateKey, key_id: str, **changes: Any) -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return _changed({**jwk, "kid": key_id, "alg": "RS256", "use": "sig"}, changes)


def _key_set_document(*jwks: object) -> bytes:
    """The shape Cloudflare serves at `/cdn-cgi/access/certs`, extra members included."""
    return json.dumps({"keys": list(jwks), "public_cert": {"kid": "x", "cert": "..."}}).encode()


@dataclass
class FakeClock:
    now: float

    def __call__(self) -> float:
        return self.now


@dataclass
class FakeKeySetEndpoint:
    """Answers each fetch with `response`: a document, or the error to raise."""

    response: bytes | Exception
    fetched_urls: list[str] = field(default_factory=list)
    before_answer: Callable[[], None] = lambda: None

    def __call__(self, url: str) -> bytes:
        self.fetched_urls.append(url)
        self.before_answer()
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@dataclass
class AccessScenario:
    endpoint: FakeKeySetEndpoint
    wall_clock: FakeClock
    monotonic_clock: FakeClock
    verifier: AccessJwtVerifier
    team: str
    audience: str
    key_id: str = "current-key"

    @property
    def issuer(self) -> str:
        return f"https://{self.team}.cloudflareaccess.com"

    def token(
        self,
        claims: dict[str, Any] | None = None,
        header: dict[str, Any] | None = None,
        sign: Callable | None = None,
    ) -> str:
        now = int(self.wall_clock.now)
        identity_claims = {
            "aud": [self.audience],
            "email": "operator@example.org",
            "exp": now + 600,
            "iat": now - 10,
            "nbf": now - 10,
            "iss": self.issuer,
            "type": "app",
            "sub": "7335d417-61da-459d-899c-0a01c76a2f94",
            "identity_nonce": "6ei69kawdKzMIAPF",
            "country": "DE",
        }
        return _jws(
            _changed({"alg": "RS256", "kid": self.key_id, "typ": "JWT"}, header or {}),
            _changed(identity_claims, claims or {}),
            sign or _rs256(_rsa_key("current")),
        )

    def serve(self, response: bytes | Exception) -> None:
        self.endpoint.response = response

    def after_cooldown(self) -> None:
        self.monotonic_clock.now += KEY_SET_REFRESH_COOLDOWN_SECONDS


@pytest.fixture
def access() -> AccessScenario:
    endpoint = FakeKeySetEndpoint(
        _key_set_document(_public_jwk(_rsa_key("current"), "current-key"))
    )
    wall_clock = FakeClock(1_800_000_000.0)
    monotonic_clock = FakeClock(5_000.0)
    verifier = AccessJwtVerifier(
        team="example-team",
        audience="example-audience-tag",
        fetch_key_set=endpoint,
        wall_clock=wall_clock,
        monotonic_clock=monotonic_clock,
    )
    return AccessScenario(
        endpoint, wall_clock, monotonic_clock, verifier, "example-team", "example-audience-tag"
    )


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({}, id="audience-list"),
        pytest.param({"aud": "example-audience-tag"}, id="audience-string"),
        pytest.param({"aud": ["another-app", "example-audience-tag"]}, id="audience-among-others"),
        pytest.param({"nbf": _ABSENT}, id="without-nbf"),
        pytest.param(
            {"note": 'a quoted "[[[[[[[[[[" and a \\ backslash'},
            id="brackets-inside-a-string-are-no-nesting",
        ),
    ],
)
def test_a_valid_identity_token_verifies_as_its_email(
    access: AccessScenario, claims: dict[str, Any]
) -> None:
    assert access.verifier.verify(access.token(claims)) == Verified("operator@example.org")
    assert access.endpoint.fetched_urls == [
        "https://example-team.cloudflareaccess.com/cdn-cgi/access/certs"
    ]


_DEEP_ARRAY = "[" * 2_000 + "]" * 2_000


@pytest.mark.parametrize(
    ("build_token", "reason"),
    [
        # Signature and algorithm
        pytest.param(
            lambda access: access.token(sign=_rs256(_rsa_key("forger"))),
            RejectionReason.INVALID_SIGNATURE,
            id="forged-signature",
        ),
        pytest.param(
            lambda access: access.token(header={"alg": "none"}, sign=lambda _: b""),
            RejectionReason.UNSUPPORTED_ALGORITHM,
            id="alg-none",
        ),
        pytest.param(
            lambda access: access.token(
                header={"alg": "HS256"}, sign=_hs256_with_public_key(_rsa_key("current"))
            ),
            RejectionReason.UNSUPPORTED_ALGORITHM,
            id="hs256-signed-with-the-public-key",
        ),
        # Claims
        pytest.param(
            lambda access: access.token({"aud": "another-app"}),
            RejectionReason.INVALID_AUDIENCE,
            id="foreign-audience-string",
        ),
        pytest.param(
            lambda access: access.token({"aud": ["another-app", "third-app"]}),
            RejectionReason.INVALID_AUDIENCE,
            id="foreign-audience-list",
        ),
        pytest.param(
            lambda access: access.token({"aud": [7]}),
            RejectionReason.INVALID_AUDIENCE,
            id="audience-list-of-non-strings",
        ),
        pytest.param(
            lambda access: access.token({"aud": []}),
            RejectionReason.INVALID_CLAIM,
            id="empty-audience-list",
        ),
        pytest.param(
            lambda access: access.token({"iss": "https://other-team.cloudflareaccess.com"}),
            RejectionReason.INVALID_ISSUER,
            id="foreign-issuer",
        ),
        pytest.param(
            lambda access: access.token({"iss": access.issuer + "/"}),
            RejectionReason.INVALID_ISSUER,
            id="issuer-with-trailing-slash",
        ),
        pytest.param(
            lambda access: access.token({"iss": 7}),
            RejectionReason.INVALID_ISSUER,
            id="issuer-not-a-string",
        ),
        *(
            pytest.param(
                lambda access, claim=claim: access.token({claim: _ABSENT}),
                RejectionReason.INVALID_CLAIM,
                id=f"missing-{claim}",
            )
            for claim in ("aud", "iss", "exp", "iat")
        ),
        *(
            pytest.param(
                lambda access, claim=claim, value=value: access.token({claim: value}),
                RejectionReason.INVALID_CLAIM,
                id=f"{claim}-as-{type(value).__name__}",
            )
            for claim, value in (
                ("exp", "1800000600"),
                ("exp", 1_800_000_600.5),
                ("exp", True),
                ("iat", None),
                ("nbf", "1799999990"),
                ("email", 7),
            )
        ),
        pytest.param(
            lambda access: access.token({"email": ""}),
            RejectionReason.INVALID_CLAIM,
            id="empty-email",
        ),
        pytest.param(
            lambda access: access.token(
                {"email": _ABSENT, "common_name": "client-id.access", "sub": ""}
            ),
            RejectionReason.SERVICE_TOKEN,
            id="service-token",
        ),
        pytest.param(
            lambda access: access.token({"common_name": "client-id.access"}),
            RejectionReason.SERVICE_TOKEN,
            id="common-name-beside-an-email",
        ),
        pytest.param(
            lambda access: access.token({"email": _ABSENT}),
            RejectionReason.SERVICE_TOKEN,
            id="no-email",
        ),
        pytest.param(
            lambda access: access.token({"type": "org"}),
            RejectionReason.WRONG_TOKEN_TYPE,
            id="type-org",
        ),
        pytest.param(
            lambda access: access.token({"type": _ABSENT}),
            RejectionReason.WRONG_TOKEN_TYPE,
            id="type-missing",
        ),
        # Headers
        pytest.param(
            lambda access: access.token(header={"kid": _ABSENT}),
            RejectionReason.INVALID_KEY_ID,
            id="kid-missing",
        ),
        pytest.param(
            lambda access: access.token(header={"kid": 7}),
            RejectionReason.INVALID_KEY_ID,
            id="kid-not-a-string",
        ),
        pytest.param(
            lambda access: access.token(header={"kid": ""}),
            RejectionReason.INVALID_KEY_ID,
            id="kid-empty",
        ),
        pytest.param(
            lambda access: access.token(header={"kid": "k" * (MAX_KEY_ID_CHARACTERS + 1)}),
            RejectionReason.INVALID_KEY_ID,
            id="kid-oversized",
        ),
        pytest.param(
            lambda access: access.token(header={"kid": "retired-key"}),
            RejectionReason.UNKNOWN_KEY_ID,
            id="kid-unknown",
        ),
        pytest.param(
            lambda access: _jws(
                '{"alg": "RS256", "kid": "current-key", "alg": "HS256"}',
                {},
                _rs256(_rsa_key("current")),
            ),
            RejectionReason.DUPLICATE_MEMBER,
            id="duplicate-alg",
        ),
        pytest.param(
            lambda access: _jws(
                '{"alg": "RS256", "kid": "current-key", "kid": "retired-key"}',
                {},
                _rs256(_rsa_key("current")),
            ),
            RejectionReason.DUPLICATE_MEMBER,
            id="duplicate-kid",
        ),
        pytest.param(
            lambda access: _jws(
                {"alg": "RS256", "kid": "current-key"},
                '{"email": "operator@example.org", "email": "intruder@example.org"}',
                _rs256(_rsa_key("current")),
            ),
            RejectionReason.DUPLICATE_MEMBER,
            id="duplicate-claim",
        ),
        *(
            pytest.param(
                lambda access, member=member: access.token(header={member: "attacker-chosen"}),
                RejectionReason.FORBIDDEN_HEADER,
                id=f"header-{member}",
            )
            for member in ("crit", "jwk", "jku", "x5u", "x5c")
        ),
        pytest.param(
            lambda access: access.token(header={"b64": False}),
            RejectionReason.FORBIDDEN_HEADER,
            id="header-b64-false",
        ),
        pytest.param(
            lambda access: access.token({"padding": "x" * MAX_TOKEN_CHARACTERS}),
            RejectionReason.TOKEN_TOO_LONG,
            id="oversized-token",
        ),
        pytest.param(
            lambda access: _jws(
                {"alg": "RS256", "kid": "current-key"},
                f'{{"deep": {_DEEP_ARRAY}}}',
                _rs256(_rsa_key("current")),
            ),
            RejectionReason.NESTING_TOO_DEEP,
            id="nesting-past-the-recursion-limit",
        ),
        pytest.param(
            lambda access: access.token(
                {"deep": json.loads("[" * MAX_JSON_NESTING_DEPTH + "]" * MAX_JSON_NESTING_DEPTH)}
            ),
            RejectionReason.NESTING_TOO_DEEP,
            id="nesting-one-past-the-bound",
        ),
        *(
            pytest.param(lambda access, raw=raw: raw, RejectionReason.MALFORMED_TOKEN, id=name)
            for name, raw in (
                ("empty", ""),
                ("one-segment", "abc"),
                ("four-segments", "a.b.c.d"),
                ("non-base64url-characters", "e30.e30.sig+nature"),
                ("impossible-base64-length", "e30.e30.a"),
                ("header-not-json", f"{_segment('not json')}.e30.c2ln"),
                ("header-not-an-object", f"{_segment('[]')}.e30.c2ln"),
                ("header-not-utf8", "_w.e30.c2ln"),
                ("non-ascii-character", "e30.e30.sïg"),
            )
        ),
        pytest.param(
            lambda access: _jws({"alg": "RS256", "kid": "current-key"}, "[]", lambda _: b"s"),
            RejectionReason.MALFORMED_TOKEN,
            id="claims-not-an-object",
        ),
        pytest.param(
            lambda access: _with_unused_signature_bits_set(access.token()),
            RejectionReason.MALFORMED_TOKEN,
            id="non-canonical-base64url",
        ),
        pytest.param(
            lambda access: access.token({"score": float("-inf")}),
            RejectionReason.MALFORMED_TOKEN,
            id="claim-with-a-non-json-constant",
        ),
        pytest.param(
            lambda access: _jws(
                {"alg": "RS256", "kid": "current-key"},
                '{"score": -1e999999}',
                _rs256(_rsa_key("current")),
            ),
            RejectionReason.MALFORMED_TOKEN,
            id="claim-overflowing-to-infinity",
        ),
    ],
)
def test_a_defective_token_is_refused_with_its_reason(
    access: AccessScenario,
    build_token: Callable[[AccessScenario], str],
    reason: RejectionReason,
) -> None:
    assert access.verifier.verify(build_token(access)) == Rejected(reason)


def test_a_token_pyjwt_cannot_decode_is_refused_as_malformed(
    access: AccessScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strict parse refuses every token PyJWT cannot decode today; should a
    later PyJWT read a segment differently, its DecodeError is still a rejection."""

    def decode_differently(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise jwt.DecodeError("this PyJWT reads the segment differently")

    monkeypatch.setattr(jwt, "decode", decode_differently)

    assert access.verifier.verify(access.token()) == Rejected(RejectionReason.MALFORMED_TOKEN)


@pytest.mark.parametrize(
    ("claim", "offset", "outcome"),
    [
        pytest.param("exp", -LEEWAY_SECONDS + 1, None, id="exp-inside-the-leeway"),
        pytest.param("exp", -LEEWAY_SECONDS, RejectionReason.EXPIRED, id="exp-at-the-leeway"),
        pytest.param("iat", LEEWAY_SECONDS, None, id="iat-at-the-leeway"),
        pytest.param(
            "iat", LEEWAY_SECONDS + 1, RejectionReason.ISSUED_IN_FUTURE, id="iat-past-the-leeway"
        ),
        pytest.param("nbf", LEEWAY_SECONDS, None, id="nbf-at-the-leeway"),
        pytest.param(
            "nbf", LEEWAY_SECONDS + 1, RejectionReason.NOT_YET_VALID, id="nbf-past-the-leeway"
        ),
    ],
)
def test_time_claims_hold_exactly_their_leeway_on_the_wall_clock(
    access: AccessScenario, claim: str, offset: int, outcome: RejectionReason | None
) -> None:
    token = access.token({claim: int(access.wall_clock.now) + offset})

    expected = Verified("operator@example.org") if outcome is None else Rejected(outcome)
    assert access.verifier.verify(token) == expected


def _defective_key_sets() -> list[Any]:
    current = _rsa_key("current")
    valid_jwk = _public_jwk(current, "current-key")
    return [
        pytest.param(KeySetFetchError("timed out"), id="fetch-failure"),
        pytest.param(b" " * MAX_KEY_SET_BYTES + b"{}", id="oversized-response"),
        pytest.param(
            _key_set_document(
                valid_jwk,
                *(_public_jwk(current, f"spare-{index}") for index in range(MAX_KEY_SET_KEYS)),
            ),
            id="too-many-keys",
        ),
        pytest.param(
            _key_set_document(valid_jwk, _public_jwk(_rsa_key("other"), "current-key")),
            id="duplicate-kid",
        ),
        pytest.param(
            _key_set_document(valid_jwk, {"kty": "oct", "kid": "shared", "k": "c2VjcmV0"}),
            id="symmetric-key",
        ),
        pytest.param(
            _key_set_document({**RSAAlgorithm.to_jwk(current, as_dict=True), "kid": "current-key"}),
            id="private-key",
        ),
        pytest.param(
            _key_set_document(valid_jwk, _public_jwk(_rsa_key("weak", 1024), "weak-key")),
            id="rsa-key-under-2048-bits",
        ),
        pytest.param(
            _key_set_document(_public_jwk(current, "current-key", alg="RS512")), id="key-alg-rs512"
        ),
        pytest.param(
            _key_set_document(_public_jwk(current, "current-key", use="enc")), id="key-use-enc"
        ),
        pytest.param(
            _key_set_document(_public_jwk(current, "current-key", key_ops=["encrypt"])),
            id="key-ops-without-verify",
        ),
        pytest.param(
            _key_set_document(_public_jwk(current, "current-key", key_ops="verify")),
            id="key-ops-not-a-list",
        ),
        pytest.param(
            _key_set_document(_public_jwk(current, "current-key", kid=7)), id="key-kid-not-a-string"
        ),
        pytest.param(
            _key_set_document(_public_jwk(current, "current-key", n=7)),
            id="key-modulus-not-a-string",
        ),
        pytest.param(
            _key_set_document(_public_jwk(current, "current-key", e="AAAA")), id="key-exponent-zero"
        ),
        pytest.param(_key_set_document("not a key"), id="key-not-an-object"),
        pytest.param(_key_set_document(), id="no-keys"),
        pytest.param(b'{"keys": {"current-key": {}}}', id="keys-not-a-list"),
        pytest.param(b'{"keys": [], "keys": []}', id="duplicate-member"),
        pytest.param(b'{"keys": [', id="malformed-json"),
        pytest.param(
            json.dumps({"keys": [valid_jwk], "extra": float("nan")}).encode(),
            id="non-json-constant",
        ),
        pytest.param(
            json.dumps({"keys": [valid_jwk]}).encode()[:-1] + b', "extra": 1e999999}',
            id="number-overflowing-to-infinity",
        ),
    ]


@pytest.mark.parametrize("response", _defective_key_sets())
def test_a_defective_key_set_is_refused_as_a_whole(
    access: AccessScenario, response: bytes | Exception
) -> None:
    access.serve(response)

    assert access.verifier.verify(access.token()) == Rejected(RejectionReason.KEY_SET_UNAVAILABLE)


def test_a_key_whose_key_ops_include_verify_is_accepted(access: AccessScenario) -> None:
    access.serve(
        _key_set_document(_public_jwk(_rsa_key("current"), "current-key", key_ops=["verify"]))
    )

    assert access.verifier.verify(access.token()) == Verified("operator@example.org")


@pytest.mark.parametrize("response", _defective_key_sets())
def test_a_defective_refresh_keeps_the_last_valid_key_set_until_its_ttl(
    access: AccessScenario, response: bytes | Exception
) -> None:
    assert access.verifier.verify(access.token()) == Verified("operator@example.org")
    access.serve(response)
    access.after_cooldown()

    refreshing = access.verifier.verify(access.token(header={"kid": "rotated-key"}))
    still_cached = access.verifier.verify(access.token())
    access.monotonic_clock.now += KEY_SET_TTL_SECONDS
    expired = access.verifier.verify(access.token())

    assert refreshing == Rejected(RejectionReason.UNKNOWN_KEY_ID)
    assert still_cached == Verified("operator@example.org")
    assert expired == Rejected(RejectionReason.KEY_SET_UNAVAILABLE)
    assert len(access.endpoint.fetched_urls) == 3


def test_the_key_set_is_cached_on_the_monotonic_clock_until_its_ttl(
    access: AccessScenario,
) -> None:
    access.verifier.verify(access.token())
    access.serve(_key_set_document(_public_jwk(_rsa_key("other"), "other-key")))

    access.monotonic_clock.now += KEY_SET_TTL_SECONDS - 1
    access.wall_clock.now += 2 * KEY_SET_TTL_SECONDS
    cached = access.verifier.verify(access.token())
    access.monotonic_clock.now += 1
    refetched = access.verifier.verify(access.token())

    assert cached == Verified("operator@example.org")
    assert refetched == Rejected(RejectionReason.UNKNOWN_KEY_ID)


def test_an_unknown_kid_refreshes_at_most_once_per_cooldown(access: AccessScenario) -> None:
    access.verifier.verify(access.token())
    access.after_cooldown()
    unknown = access.token(header={"kid": "rotated-key"})

    for _ in range(3):
        access.verifier.verify(unknown)
    fetches_within_cooldown = len(access.endpoint.fetched_urls)
    access.after_cooldown()
    access.verifier.verify(unknown)

    assert fetches_within_cooldown == 2
    assert len(access.endpoint.fetched_urls) == 3


def test_a_rotated_key_verifies_once_its_unknown_kid_refreshed_the_key_set(
    access: AccessScenario,
) -> None:
    access.verifier.verify(access.token())
    access.serve(
        _key_set_document(
            _public_jwk(_rsa_key("current"), "current-key"),
            _public_jwk(_rsa_key("other"), "rotated-key"),
        )
    )
    access.after_cooldown()

    rotated = access.token(header={"kid": "rotated-key"}, sign=_rs256(_rsa_key("other")))

    assert access.verifier.verify(rotated) == Verified("operator@example.org")


def test_parallel_unknown_kids_share_one_fetch_and_each_fails_closed(
    access: AccessScenario,
) -> None:
    access.verifier.verify(access.token())
    access.after_cooldown()
    fetch_started, release_fetch = threading.Event(), threading.Event()

    def hold_the_fetch() -> None:
        fetch_started.set()
        assert release_fetch.wait(timeout=10)

    access.endpoint.before_answer = hold_the_fetch
    unknown = access.token(header={"kid": "rotated-key"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        refreshing = pool.submit(access.verifier.verify, unknown)
        assert fetch_started.wait(timeout=10)
        while_refreshing = [
            outcome.result(timeout=10)
            for outcome in [pool.submit(access.verifier.verify, unknown) for _ in range(7)]
        ]
        release_fetch.set()
        outcomes = [refreshing.result(timeout=10), *while_refreshing]

    assert outcomes == [Rejected(RejectionReason.UNKNOWN_KEY_ID)] * 8
    assert len(access.endpoint.fetched_urls) == 2


@pytest.mark.parametrize(
    ("team", "audience", "refused"),
    [
        *(
            pytest.param(team, "example-audience-tag", "team", id=f"team-{team!r}")
            for team in ("", "Example", "example.team", "example/team", "example-team\n", "t" * 64)
        ),
        pytest.param("example-team", "", "audience", id="empty-audience"),
    ],
)
def test_a_team_name_outside_the_cloudflare_pattern_or_an_empty_audience_is_refused(
    access: AccessScenario, team: str, audience: str, refused: str
) -> None:
    with pytest.raises(ValueError, match=refused):
        AccessJwtVerifier(
            team=team,
            audience=audience,
            fetch_key_set=access.endpoint,
            wall_clock=access.wall_clock,
            monotonic_clock=access.monotonic_clock,
        )


# The real HTTPS boundary, served from loopback under a self-signed certificate.


_TRICKLE_INTERVAL_SECONDS = 0.05
_TRICKLED_BYTES = 200
"""Ten seconds of trickle; the fetch under test is given ten intervals."""


@dataclass
class HttpsKeySetServer:
    base_url: str
    requested_paths: list[str]


def _self_signed_loopback_certificate(directory: Path) -> tuple[Path, Path]:
    key = _rsa_key("loopback-tls")
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certificate_path, key_path = directory / "cert.pem", directory / "key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path


@pytest.fixture
def https_key_set_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[HttpsKeySetServer]:
    certificate_path, key_path = _self_signed_loopback_certificate(tmp_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate_path))
    requested_paths: list[str] = []

    class KeySetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested_paths.append(self.path)
            if self.path == "/moved":
                self.send_response(302)
                self.send_header("Location", "/certs")
                self.end_headers()
            elif self.path == "/trickle":
                self._trickle(b" " * _TRICKLED_BYTES)
            elif self.path == "/oversized":
                self._answer(b" " * (2 * MAX_KEY_SET_BYTES))
            else:
                self._answer(_key_set_document(_public_jwk(_rsa_key("current"), "current-key")))

        def _answer(self, body: bytes) -> None:
            self._start_body(len(body))
            # The fetch may hang up once it read its limit.
            with contextlib.suppress(OSError):
                self.wfile.write(body)

        def _trickle(self, body: bytes) -> None:
            """One byte per interval: each read finishes well inside the
            fetch's socket timeout, the whole answer far past its deadline."""
            self._start_body(len(body))
            with contextlib.suppress(OSError):
                for byte in body:
                    self.wfile.write(bytes([byte]))
                    time.sleep(_TRICKLE_INTERVAL_SECONDS)

        def _start_body(self, length: int) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(length))
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate_path, key_path)
    server = HTTPServer(("127.0.0.1", 0), KeySetHandler)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    try:
        yield HttpsKeySetServer(f"https://127.0.0.1:{server.server_port}", requested_paths)
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=10)


def test_https_fetch_returns_the_served_key_set(https_key_set_server: HttpsKeySetServer) -> None:
    document = fetch_key_set_over_https(f"{https_key_set_server.base_url}/certs")

    assert json.loads(document)["keys"][0]["kid"] == "current-key"


def test_https_fetch_gives_up_on_a_trickling_answer_at_its_deadline(
    https_key_set_server: HttpsKeySetServer,
) -> None:
    with pytest.raises(KeySetFetchError):
        fetch_key_set_over_https(
            f"{https_key_set_server.base_url}/trickle",
            deadline_seconds=10 * _TRICKLE_INTERVAL_SECONDS,
        )


def test_https_fetch_reads_at_most_one_byte_past_the_key_set_limit(
    https_key_set_server: HttpsKeySetServer,
) -> None:
    document = fetch_key_set_over_https(f"{https_key_set_server.base_url}/oversized")

    assert len(document) == MAX_KEY_SET_BYTES + 1


def test_https_fetch_refuses_a_certificate_the_system_does_not_trust(
    https_key_set_server: HttpsKeySetServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE")

    with pytest.raises(KeySetFetchError):
        fetch_key_set_over_https(f"{https_key_set_server.base_url}/certs")


def test_https_fetch_never_follows_a_redirect(https_key_set_server: HttpsKeySetServer) -> None:
    with pytest.raises(KeySetFetchError):
        fetch_key_set_over_https(f"{https_key_set_server.base_url}/moved")

    assert https_key_set_server.requested_paths == ["/moved"]


@pytest.mark.parametrize("url", ["http://127.0.0.1:9/certs", "file:///etc/hostname"])
def test_fetch_refuses_every_scheme_but_https(url: str) -> None:
    with pytest.raises(KeySetFetchError):
        fetch_key_set_over_https(url)
