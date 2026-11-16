import datetime
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

DNS_NAMES = ["localhost"]
IP_ADDRESSES = ["127.0.0.1"]

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
now = datetime.datetime.now(datetime.timezone.utc)

san = [x509.DNSName(n) for n in DNS_NAMES] + [
    x509.IPAddress(ipaddress.ip_address(ip)) for ip in IP_ADDRESSES
]

cert = (
    x509.CertificateBuilder()
    .subject_name(name)
    .issuer_name(name)                       
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(minutes=1))
    .not_valid_after(now + datetime.timedelta(days=365))
    .add_extension(x509.SubjectAlternativeName(san), critical=False)
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
    )
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)

with open("server.key", "wb") as f:
    f.write(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
with open("server.crt", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print("Wrote server.key (keep private) and server.crt (give to clients).")