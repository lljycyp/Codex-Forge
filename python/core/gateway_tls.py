"""One Forge-specific CA. Clients trust its public certificate for this process only."""

import datetime as dt
import ipaddress
import json
import ssl
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _name(label):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])


def _pem(key):
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _certificate(subject, issuer, key, days):
    now = dt.datetime.now(dt.UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=days))
    )


def _make_authority():
    key = ec.generate_private_key(ec.SECP256R1())
    name = _name("Codex Forge Gateway CA")
    cert = (
        _certificate(name, name, key, 3650)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
        )
        .sign(key, hashes.SHA256())
    )
    return json.dumps([_pem(key).decode(), cert.public_bytes(serialization.Encoding.PEM).decode()]).encode()


def _authority(store):
    key_pem, ca_pem = json.loads(store.secret("tls-authority", _make_authority))
    public = store.directory / "forge-gateway-ca.pem"
    if not public.is_file() or public.read_bytes() != ca_pem.encode():
        public.write_bytes(ca_pem.encode())
    return key_pem, ca_pem


def ensure_public_ca(store):
    _authority(store)
    return store.directory / "forge-gateway-ca.pem"


def server_tls(store, address):
    key_pem, ca_pem = _authority(store)
    ca_key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    assert isinstance(ca_key, ec.EllipticCurvePrivateKey)
    ca = x509.load_pem_x509_certificate(ca_pem.encode())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        _certificate(_name("Codex Forge"), ca.subject, leaf_key, 180)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), critical=False
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # The issuing key never leaves DPAPI storage. The transient leaf key lives in the user temp directory.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as transient:
        transient.write(_pem(leaf_key) + leaf.public_bytes(serialization.Encoding.PEM))
    try:
        ctx.load_cert_chain(transient.name)
    finally:
        Path(transient.name).unlink(missing_ok=True)
    return ctx
