"""Mail delivery behind one method. The production provider is picked later; SMTP with STARTTLS is the generic option."""
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str) -> None: ...


class ConsoleMailer:
    """Dev only: prints the mail so the login code can be read from the terminal."""

    def send(self, to: str, subject: str, text: str) -> None:
        print(f"--- mail to {to}\nSubject: {subject}\n\n{text}---", flush=True)


class ListMailer:
    """Tests: keeps every mail; set `fail` to an exception to simulate a provider outage."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail: Exception | None = None

    def send(self, to: str, subject: str, text: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append((to, subject, text))


class SmtpMailer:
    def __init__(self, host: str, port: int, user: str, password: str, mail_from: str) -> None:
        self.host, self.port, self.user, self.password, self.mail_from = host, port, user, password, mail_from

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.mail_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
