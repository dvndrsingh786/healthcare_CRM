"""Provider abstraction for email / SMS / push delivery.

Real providers (SES, Twilio, FCM...) are not wired up in sprint 1. ConsoleProvider stands in:
it "delivers" by keeping the message in memory and logging only non-sensitive facts.
Swapping in a real provider means implementing `send` and changing get_provider().
"""
import logging
import secrets
from dataclasses import dataclass

logger = logging.getLogger("hcrm.messaging")


@dataclass
class OutgoingMessage:
    channel: str          # EMAIL, SMS or PUSH
    to: str               # address, phone number or push token
    template_key: str
    subject: str
    body: str
    idempotency_key: str  # passed to the provider so a retried send is not delivered twice


class ProviderError(Exception):
    """The provider failed. `temporary` says whether a retry might work."""

    def __init__(self, code, temporary=True):
        super().__init__(code)
        self.code = code
        self.temporary = temporary


class ConsoleProvider:
    def __init__(self):
        self.sent = []  # used by tests and local demos
        self.delivered = {}  # idempotency_key -> provider message id

    def send(self, message: OutgoingMessage):
        # Like real providers: the same idempotency key is delivered once; a retry gets the same id back.
        if message.idempotency_key in self.delivered:
            return self.delivered[message.idempotency_key]
        self.sent.append(message)
        # Never log the address or the body: they can contain personal data or a reset link.
        logger.info("message_sent", extra={"channel": message.channel, "template": message.template_key})
        self.delivered[message.idempotency_key] = "console-" + secrets.token_hex(8)
        return self.delivered[message.idempotency_key]


_provider = ConsoleProvider()


def get_provider():
    return _provider


def set_provider(provider):
    """Used by tests (e.g. a failing provider) and by future real integrations."""
    global _provider
    _provider = provider
