"""
Fake outside world for 03_absurd.py. Three services with three different guarantees:
  FakeStripe     dedupes on idempotency_key          -> on_unknown=rerun is safe
  FakeInventory  no dedupe, but lookup by reference  -> on_unknown=reconcile(lookup)
  FakeMailer     no dedupe, no lookup                -> on_unknown=at_most_once
Each has a one-shot `crash_next`: the world changes, then the caller "dies" before hearing back.
"""
from dataclasses import dataclass, field

from tally import Ok

DECLINED_CARD = "4000-0000-0000-0002"


class SimulatedCrash(Exception):
    """The process died after the world changed but before tally recorded the answer."""


class CardDeclined(Exception):
    pass


@dataclass
class FakeStripe:
    charges: dict[str, dict] = field(default_factory=dict)  # idempotency_key -> charge
    crash_next: bool = False

    def charge(self, amount: int, card: str, idempotency_key: str) -> dict:
        if idempotency_key in self.charges: return self.charges[idempotency_key]  # dedupe: replay, no new charge
        if card == DECLINED_CARD: raise CardDeclined("card_declined")
        receipt = {"charge_id": f"ch_{len(self.charges) + 1}", "amount": amount}
        self.charges[idempotency_key] = receipt
        if self.crash_next:
            self.crash_next = False
            raise SimulatedCrash("died after stripe charged")
        return receipt


@dataclass
class FakeInventory:
    reservations: list[dict] = field(default_factory=list)  # appends every call: reserving twice holds two units
    crash_next: bool = False

    def reserve(self, sku: str, reference: str) -> dict:
        reservation = {"reservation_id": f"res_{len(self.reservations) + 1}", "sku": sku, "reference": reference}
        self.reservations.append(reservation)
        if self.crash_next:
            self.crash_next = False
            raise SimulatedCrash("died after inventory reserved")
        return reservation

    def lookup(self, reference: str) -> Ok[dict] | None:
        found = [reservation for reservation in self.reservations if reservation["reference"] == reference]
        return Ok(found[0]) if found else None


@dataclass
class FakeMailer:
    sent: list[str] = field(default_factory=list)  # every call sends: no dedupe, no way to ask "did I send it?"
    crash_next: bool = False

    def send(self, to: str, body: str) -> None:
        self.sent.append(f"{to}: {body}")
        if self.crash_next:
            self.crash_next = False
            raise SimulatedCrash("died after smtp sent")


@dataclass
class World:
    stripe: FakeStripe = field(default_factory=FakeStripe)
    inventory: FakeInventory = field(default_factory=FakeInventory)
    mailer: FakeMailer = field(default_factory=FakeMailer)

    def counts(self) -> tuple[int, int, int]:
        return len(self.stripe.charges), len(self.inventory.reservations), len(self.mailer.sent)
