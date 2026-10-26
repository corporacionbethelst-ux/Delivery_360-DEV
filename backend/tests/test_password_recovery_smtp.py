"""Real pinned SMTP client against a non-relaying loopback TLS sink."""

import asyncio
import base64
import ipaddress
import ssl
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser

import aiosmtplib
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tests.test_password_recovery_email import smtp  # noqa: F401
from app.core import email_service as mail
from app.core.config import settings

REAL_SMTP = aiosmtplib.SMTP


@pytest.fixture
async def local_smtp(smtp, tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "smtp.crt", tmp_path / "smtp.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    monkeypatch.setattr(mail.aiosmtplib, "SMTP", REAL_SMTP)
    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "SMTP_TIMEOUT_SECONDS", 2.0)

    @asynccontextmanager
    async def server(
        *, implicit=False, trusted=True, advertise_tls=True, reject_auth=False
    ):
        # Trust is confined to this test's process environment, never app settings.
        monkeypatch.setenv(
            "SSL_CERT_FILE", str(cert_file if trusted else tmp_path / "absent-ca.pem")
        )
        commands, credentials, messages = [], [], []
        tasks, writers = set(), set()
        closed = asyncio.Event()

        async def handle(reader, writer):
            tasks.add(asyncio.current_task())
            writers.add(writer)

            async def reply(value):
                writer.write(value.encode("ascii") + b"\r\n")
                await writer.drain()

            try:
                await reply("220 localhost test sink")
                authenticated = False
                while raw := await reader.readline():
                    line = raw.decode("ascii").rstrip("\r\n")
                    verb = line.split(" ", 1)[0].upper()
                    encrypted = writer.get_extra_info("ssl_object") is not None
                    commands.append((verb, encrypted))
                    if verb in ("EHLO", "HELO"):
                        await reply("250-localhost")
                        if not encrypted and advertise_tls:
                            await reply("250-STARTTLS")
                        if encrypted:
                            await reply("250-AUTH PLAIN")
                        await reply("250 SIZE 100000")
                    elif verb == "STARTTLS":
                        await reply("220 Ready for TLS")
                        transport = writer.transport
                        try:
                            await writer.start_tls(context, ssl_handshake_timeout=2)
                        except AttributeError:
                            # _replace_writer dereferences None if start_tls
                            # returned no transport after peer rejection.
                            if writer.transport is not None:
                                raise
                            return
                        finally:
                            if writer.transport is None:
                                # Python 3.12 may lose the transport on a rejected
                                # handshake, including exceptional exits.
                                writer._transport = transport
                    elif verb == "AUTH":
                        if not encrypted:
                            await reply("530 TLS required")
                            continue
                        credentials.append(base64.b64decode(line.split(" ")[-1]))
                        authenticated = not reject_auth
                        await reply(
                            "235 Authenticated"
                            if authenticated
                            else "535 Rejected test credentials"
                        )
                    elif verb in ("MAIL", "RCPT"):
                        await reply(
                            "250 Accepted"
                            if authenticated
                            else "530 Authenticate first"
                        )
                    elif verb == "DATA" and authenticated:
                        await reply("354 End with dot")
                        body = bytearray()
                        while (data := await reader.readline()) not in (b".\r\n", b""):
                            body.extend(data[1:] if data.startswith(b"..") else data)
                        messages.append(
                            BytesParser(policy=policy.default).parsebytes(bytes(body))
                        )
                        await reply("250 Stored only in test memory")
                    elif verb == "QUIT":
                        await reply("221 Bye")
                        return
                    else:
                        await reply("250 OK")
            except (ConnectionError, ssl.SSLError):
                pass
            finally:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 0.5)
                except (ConnectionError, ssl.SSLError, asyncio.TimeoutError):
                    pass
                writers.discard(writer)
                tasks.discard(asyncio.current_task())
                closed.set()

        listener = await asyncio.start_server(
            handle, "127.0.0.1", 0, ssl=context if implicit else None
        )
        monkeypatch.setattr(settings, "SMTP_PORT", listener.sockets[0].getsockname()[1])
        monkeypatch.setattr(settings, "SMTP_SSL", implicit)
        monkeypatch.setattr(settings, "SMTP_TLS", not implicit)
        try:
            yield commands, credentials, messages, closed
        finally:
            listener.close()
            for writer in list(writers):
                writer.close()
            await asyncio.wait_for(listener.wait_closed(), 3)
            if tasks:
                await asyncio.wait_for(
                    asyncio.gather(*list(tasks), return_exceptions=True), 3
                )

    return server


@pytest.mark.asyncio
@pytest.mark.parametrize("implicit", [False, True])
async def test_real_authenticated_tls_accepts_multipart_message(local_smtp, implicit):
    async with local_smtp(implicit=implicit) as (
        commands,
        credentials,
        messages,
        closed,
    ):
        link = mail.password_reset_link("private-test-token")
        assert await mail.send_reset_email("recipient@example.com", link)
        assert credentials == [b"\x00test-login\x00test-only-password"]
        assert len(messages) == 1
        assert messages[0]["To"] == "recipient@example.com"
        assert link in messages[0].get_body(preferencelist=("plain",)).get_content()
        assert link in messages[0].get_body(preferencelist=("html",)).get_content()
        assert all(
            encrypted
            for verb, encrypted in commands
            if verb in ("AUTH", "MAIL", "RCPT", "DATA")
        )
        assert (
            ("STARTTLS", False) in commands
            if not implicit
            else all(encrypted for _, encrypted in commands)
        )


@pytest.mark.asyncio
async def test_real_untrusted_certificate_sends_no_credentials_or_body(
    local_smtp, caplog
):
    async with local_smtp(trusted=False) as (commands, credentials, messages, closed):
        assert not await mail.send_reset_email(
            "recipient@example.com", mail.password_reset_link("private-test-token")
        )
        assert not credentials and not messages
        await asyncio.wait_for(closed.wait(), 1)
        assert not any(verb in ("AUTH", "MAIL", "DATA") for verb, _ in commands)
        assert "recipient@example.com" not in caplog.text
        assert "private-test-token" not in caplog.text


@pytest.mark.asyncio
async def test_real_server_without_starttls_never_downgrades_to_plaintext(local_smtp):
    async with local_smtp(advertise_tls=False) as (
        commands,
        credentials,
        messages,
        closed,
    ):
        assert not await mail.send_reset_email(
            "recipient@example.com", mail.password_reset_link("private-test-token")
        )
        assert not credentials and not messages
        await asyncio.wait_for(closed.wait(), 1)
        assert not any(verb in ("AUTH", "MAIL", "DATA") for verb, _ in commands)


@pytest.mark.asyncio
async def test_real_auth_rejection_is_a_failed_delivery(local_smtp):
    async with local_smtp(reject_auth=True) as (_, credentials, messages, closed):
        assert not await mail.send_reset_email(
            "recipient@example.com", mail.password_reset_link("private-test-token")
        )
        assert credentials and not messages
        await asyncio.wait_for(closed.wait(), 1)
