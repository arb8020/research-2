"""
Order fulfillment as durable effects.
exactly once = tally's intent log + the other side deduping the idempotency key; neither alone is enough.
"""
import tempfile
from pathlib import Path

from _stripe import DECLINED_CARD, CardDeclined, SimulatedCrash, World

from tally import EffectFailed, Err, Ok, StepCtx, at_most_once, open_store, reconcile, rerun, start

GOOD_CARD = "4242-4242-4242-4242"


def charge(ctx: StepCtx, world: World, order: dict, *, idem_key: str, out: Path) -> Ok[dict] | Err[str]:
    try:
        receipt = world.stripe.charge(order["amount"], order["card"], idempotency_key=idem_key)  # tally key IS the idem key
    except CardDeclined as declined:
        return Err(str(declined))
    return Ok(receipt)


def reserve(ctx: StepCtx, world: World, order: dict, *, idem_key: str, out: Path) -> Ok[dict]:
    return Ok(world.inventory.reserve(order["sku"], reference=idem_key))


def send_email(ctx: StepCtx, world: World, order: dict, *, idem_key: str, out: Path) -> Ok[None]:
    world.mailer.send(order["email"], f"order {order['id']} is on its way")
    return Ok(None)


def fulfill(ctx: StepCtx, world: World, order: dict, attempt: int) -> None:
    ctx.effect(f"charge:{order['id']}:{attempt}", charge, world, order, on_unknown=rerun)
    ctx.effect(f"reserve:{order['id']}", reserve, world, order, on_unknown=reconcile(world.inventory.lookup))
    ctx.effect(f"email:{order['id']}", send_email, world, order, on_unknown=at_most_once)


def order(order_id: int, card: str = GOOD_CARD) -> dict:
    return {"id": order_id, "amount": 1999, "card": card, "sku": "mug", "email": "ada@example.com"}


def report(label: str, world: World, note: str) -> None:
    charges, reservations, sends = world.counts()
    print(f"{label:34s} charges={charges} reservations={reservations} emails={sends}  {note}")


def happy_path_then_rerun(root: Path) -> None:
    world, store = World(), open_store(root / "happy")
    first = start(store)
    fulfill(first, world, order(1), attempt=1)
    report("1 happy path", world, f"ran={first.ran}")
    assert world.counts() == (1, 1, 1)

    second = start(store)
    fulfill(second, world, order(1), attempt=1)
    report("2 rerun fulfill", world, "ran=[] (all recorded)")
    assert second.ran == []
    assert world.counts() == (1, 1, 1)


def crash_then_retry(root: Path, label: str, crash_service: str) -> tuple[World, Exception | None]:
    """Crash inside one service right after it changed the world, then retry fulfill in a 'new process'."""
    world, store = World(), open_store(root / crash_service)
    setattr(getattr(world, crash_service), "crash_next", True)
    try:
        fulfill(start(store), world, order(2), attempt=1)
        raise AssertionError("expected a simulated crash")
    except SimulatedCrash:
        pass
    retry = start(store)
    try:
        fulfill(retry, world, order(2), attempt=1)
    except EffectFailed as failed:
        report(label, world, f"retry ran={retry.ran}, raised EffectFailed({failed.error!r})")
        return world, failed
    report(label, world, f"retry ran={retry.ran}")
    return world, None


def declined_then_new_attempt(root: Path) -> None:
    world, store = World(), open_store(root / "declined")
    declined_errors = []
    for _replay in range(2):  # the second call replays the recorded Err; stripe is not asked again
        try:
            fulfill(start(store), world, order(3, card=DECLINED_CARD), attempt=1)
            raise AssertionError("expected a decline")
        except EffectFailed as failed:
            declined_errors.append((failed.key, failed.error))
    assert declined_errors == [("charge:3:1", "card_declined")] * 2
    retry = start(store)
    fulfill(retry, world, order(3, card=GOOD_CARD), attempt=2)
    report("6 declined, then attempt 2", world, f"attempt 1 -> {declined_errors[0]}, attempt 2 ran={retry.ran}")
    assert list(world.stripe.charges) == ["charge:3:2"]
    assert world.counts() == (1, 1, 1)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        happy_path_then_rerun(root)

        world, failed = crash_then_retry(root, "3 crash after stripe charged", "stripe")
        assert failed is None
        assert world.counts() == (1, 1, 1)  # rerun reused the idem key; stripe deduped

        world, failed = crash_then_retry(root, "4 crash after inventory reserved", "inventory")
        assert failed is None
        assert world.counts() == (1, 1, 1)  # reconcile found the reservation; did not reserve again

        world, failed = crash_then_retry(root, "5 crash after smtp sent", "mailer")
        assert failed is not None
        assert failed.error == "unknown after crash"
        assert world.counts() == (1, 1, 1)  # at_most_once refused to send again; a human decides

        declined_then_new_attempt(root)
    print("03_absurd: all assertions passed")


if __name__ == "__main__":
    main()
