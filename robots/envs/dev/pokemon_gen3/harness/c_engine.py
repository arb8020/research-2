"""ctypes boundary for the native Gen 3 battle core."""

from __future__ import annotations

import ctypes
import multiprocessing
import multiprocessing.connection
import subprocess
from dataclasses import dataclass
from pathlib import Path

from teams import TeamSpec

ABI_VERSION = 12
TEAM_SIZE = 6
MOVE_SLOTS = 4
SIDE_COUNT = 2
MAX_EVENTS = 32
GEN3_OK = 0
GEN3_UNSUPPORTED_ACTION = 5
STAT_NAMES = ("hp", "atk", "def", "spa", "spd", "spe")
_ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"


class PokemonSet(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("species_id", ctypes.c_uint16),
        ("item_id", ctypes.c_uint16),
        ("ability_id", ctypes.c_uint16),
        ("move_ids", ctypes.c_uint16 * MOVE_SLOTS),
        ("stats", ctypes.c_uint16 * 6),
        ("max_pp", ctypes.c_uint16 * MOVE_SLOTS),
        ("level", ctypes.c_uint8),
        ("gender", ctypes.c_uint8),
        ("happiness", ctypes.c_uint8),
        ("shiny", ctypes.c_uint8),
    ]


class BattleTeam(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("pokemon", PokemonSet * TEAM_SIZE),
    ]


class BattleInit(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("teams", BattleTeam * SIDE_COUNT),
        ("seed", ctypes.c_uint16 * 4),
    ]


class PokemonSnapshot(ctypes.Structure):
    _fields_ = [
        ("set", PokemonSet),
        ("hp", ctypes.c_uint16),
        ("pp", ctypes.c_uint16 * MOVE_SLOTS),
        ("status", ctypes.c_uint8),
        ("protect_counter", ctypes.c_uint8),
        ("toxic_counter", ctypes.c_uint8),
        ("leech_seeded", ctypes.c_uint8),
        ("stat_stages", ctypes.c_int8 * 5),
    ]


class BattleEvent(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_uint8),
        ("side", ctypes.c_uint8),
        ("status", ctypes.c_uint8),
        ("amount", ctypes.c_uint8),
        ("species_id", ctypes.c_uint16),
        ("move_id", ctypes.c_uint16),
        ("hp", ctypes.c_uint16),
        ("max_hp", ctypes.c_uint16),
    ]


class BattleSnapshot(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("struct_size", ctypes.c_uint32),
        ("pokemon", (PokemonSnapshot * TEAM_SIZE) * SIDE_COUNT),
        ("seed", ctypes.c_uint16 * 4),
        ("turn", ctypes.c_uint32),
        ("event_count", ctypes.c_uint16),
        ("force_switch_side", ctypes.c_int8),
        ("spikes", ctypes.c_uint8 * SIDE_COUNT),
        ("resume_residuals", ctypes.c_uint8),
        ("done", ctypes.c_uint8),
        ("winner_side", ctypes.c_int8),
        ("events", BattleEvent * MAX_EVENTS),
    ]


@dataclass(frozen=True)
class NativeState:
    legal_p1: tuple[int, ...]
    legal_p2: tuple[int, ...]
    snapshot: dict[str, object]
    unsupported: str | None = None


class NativeEngineCrash(RuntimeError):
    """The isolated native engine died without returning through its ABI."""

    def __init__(self, operation: str, exitcode: int | None) -> None:
        self.operation = operation
        self.exitcode = exitcode
        if exitcode is not None and exitcode < 0:
            reason = f"signal {-exitcode}"
        elif exitcode is None:
            reason = "unknown process termination"
        else:
            reason = f"exit status {exitcode}"
        super().__init__(f"native engine died during {operation}: {reason}")


def build_engine_library() -> Path:
    """Build the shared library through its checked-in strict Makefile."""
    subprocess.run(
        ["make", "-C", str(_ENGINE_DIR), "libpokemon_gen3.so"],
        check=True,
    )
    return _ENGINE_DIR / "libpokemon_gen3.so"


class NativeEngine:
    def __init__(self, library: Path | None = None) -> None:
        default_library = _ENGINE_DIR / "libpokemon_gen3.so"
        selected = library or default_library
        sources = (
            _ENGINE_DIR / "gen3_abi.c",
            _ENGINE_DIR / "gen3_abi.h",
            _ENGINE_DIR / "Makefile",
        )
        stale = not selected.exists() or any(
            source.stat().st_mtime > selected.stat().st_mtime
            for source in sources
        )
        if library is None and stale:
            selected = build_engine_library()
        self._lib = ctypes.CDLL(str(selected))
        self._handle = ctypes.c_void_p()
        self._configure_abi()
        self._check_layouts()

    def start(
        self, teams: tuple[TeamSpec, TeamSpec], seed: tuple[int, int, int, int],
    ) -> NativeState:
        if self._handle.value is not None:
            raise RuntimeError("native battle already started")
        init = _build_init(teams, seed)
        error = ctypes.create_string_buffer(256)
        result = self._lib.gen3_battle_create(
            ctypes.byref(init), ctypes.byref(self._handle), error, len(error)
        )
        if result != GEN3_OK:
            raise RuntimeError(error.value.decode() or f"gen3_battle_create: {result}")
        state = self.state()
        if self._switch_slice_supported():
            return state
        return NativeState(
            state.legal_p1,
            state.legal_p2,
            state.snapshot,
            "team abilities are outside the switch-only capability set",
        )

    def turn(self, action_p1: int, action_p2: int) -> NativeState:
        self._require_started()
        result = self._lib.gen3_battle_turn(
            self._handle, action_p1, action_p2
        )
        if result == GEN3_UNSUPPORTED_ACTION:
            state = self.state()
            return NativeState(
                state.legal_p1,
                state.legal_p2,
                state.snapshot,
                f"actions ({action_p1}, {action_p2}) are not implemented",
            )
        if result != GEN3_OK:
            raise RuntimeError(f"gen3_battle_turn failed: {result}")
        return self.state()

    def state(self) -> NativeState:
        self._require_started()
        snapshot = BattleSnapshot()
        result = self._lib.gen3_battle_snapshot(
            self._handle, ctypes.byref(snapshot)
        )
        if result != GEN3_OK:
            raise RuntimeError(f"gen3_battle_snapshot failed: {result}")
        return NativeState(
            _actions_from_mask(self._legal_mask(0)),
            _actions_from_mask(self._legal_mask(1)),
            _snapshot_json(snapshot),
        )

    def close(self) -> None:
        if self._handle.value is not None:
            self._lib.gen3_battle_destroy(self._handle)
            self._handle = ctypes.c_void_p()

    def _legal_mask(self, side: int) -> int:
        mask = ctypes.c_uint16()
        result = self._lib.gen3_battle_legal_actions(
            self._handle, side, ctypes.byref(mask)
        )
        if result != GEN3_OK:
            raise RuntimeError(f"gen3_battle_legal_actions failed: {result}")
        return mask.value

    def _switch_slice_supported(self) -> bool:
        supported = ctypes.c_uint8()
        result = self._lib.gen3_battle_switch_slice_supported(
            self._handle, ctypes.byref(supported)
        )
        if result != GEN3_OK:
            raise RuntimeError(
                f"gen3_battle_switch_slice_supported failed: {result}"
            )
        return bool(supported.value)

    def _require_started(self) -> None:
        if self._handle.value is None:
            raise RuntimeError("native battle has not started")

    def _configure_abi(self) -> None:
        self._lib.gen3_abi_version.restype = ctypes.c_uint32
        for name in (
            "gen3_sizeof_pokemon_set", "gen3_sizeof_battle_team",
            "gen3_sizeof_battle_init", "gen3_sizeof_battle_snapshot",
        ):
            getattr(self._lib, name).restype = ctypes.c_size_t
        self._lib.gen3_battle_create.argtypes = [
            ctypes.POINTER(BattleInit), ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._lib.gen3_battle_create.restype = ctypes.c_int
        self._lib.gen3_battle_destroy.argtypes = [ctypes.c_void_p]
        self._lib.gen3_battle_turn.argtypes = [
            ctypes.c_void_p, ctypes.c_int8, ctypes.c_int8,
        ]
        self._lib.gen3_battle_turn.restype = ctypes.c_int
        self._lib.gen3_battle_legal_actions.argtypes = [
            ctypes.c_void_p, ctypes.c_uint8, ctypes.POINTER(ctypes.c_uint16),
        ]
        self._lib.gen3_battle_legal_actions.restype = ctypes.c_int
        self._lib.gen3_battle_switch_slice_supported.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8),
        ]
        self._lib.gen3_battle_switch_slice_supported.restype = ctypes.c_int
        self._lib.gen3_battle_snapshot.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(BattleSnapshot),
        ]
        self._lib.gen3_battle_snapshot.restype = ctypes.c_int

    def _check_layouts(self) -> None:
        expected = (
            ("gen3_sizeof_pokemon_set", PokemonSet),
            ("gen3_sizeof_battle_team", BattleTeam),
            ("gen3_sizeof_battle_init", BattleInit),
            ("gen3_sizeof_battle_snapshot", BattleSnapshot),
        )
        if self._lib.gen3_abi_version() != ABI_VERSION:
            raise RuntimeError("native Gen 3 ABI version mismatch")
        for function, structure in expected:
            if getattr(self._lib, function)() != ctypes.sizeof(structure):
                raise RuntimeError(f"ctypes layout mismatch for {structure.__name__}")


def _native_worker(connection, library: str | None) -> None:
    """Own one native handle in a process where C assertions may stay fatal."""
    engine: NativeEngine | None = None
    try:
        engine = NativeEngine(Path(library) if library is not None else None)
        connection.send(("ready", None))
        while True:
            operation, arguments = connection.recv()
            if operation == "start":
                result = engine.start(*arguments)
            elif operation == "turn":
                result = engine.turn(*arguments)
            elif operation == "state":
                result = engine.state()
            elif operation == "close":
                connection.send(("ok", None))
                return
            else:
                raise RuntimeError(f"unknown native worker operation: {operation}")
            connection.send(("ok", result))
    except (EOFError, BrokenPipeError):
        return
    except Exception as error:
        try:
            connection.send(("error", f"{type(error).__name__}: {error}"))
        except (EOFError, BrokenPipeError):
            pass
    finally:
        if engine is not None:
            engine.close()
        connection.close()


class IsolatedNativeEngine:
    """RPC boundary that contains fatal C failures without weakening asserts."""

    _TIMEOUT_SECONDS = 30.0

    def __init__(self, library: Path | None = None) -> None:
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self._connection = parent
        self._process = context.Process(
            target=_native_worker,
            args=(child, str(library) if library is not None else None),
            name="gen3-native-engine",
        )
        self._process.start()
        child.close()
        self._receive("startup")

    def start(
        self, teams: tuple[TeamSpec, TeamSpec], seed: tuple[int, int, int, int],
    ) -> NativeState:
        return self._call("start", teams, seed)

    def turn(self, action_p1: int, action_p2: int) -> NativeState:
        return self._call("turn", action_p1, action_p2)

    def state(self) -> NativeState:
        return self._call("state")

    def close(self) -> None:
        if self._process.is_alive():
            try:
                self._connection.send(("close", ()))
                self._receive("close")
            except (BrokenPipeError, EOFError, NativeEngineCrash, RuntimeError):
                pass
        self._connection.close()
        self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)

    def _call(self, operation: str, *arguments) -> NativeState:
        if not self._process.is_alive():
            raise NativeEngineCrash(operation, self._process.exitcode)
        try:
            self._connection.send((operation, arguments))
        except (BrokenPipeError, EOFError) as error:
            self._process.join(timeout=1)
            raise NativeEngineCrash(operation, self._process.exitcode) from error
        return self._receive(operation)

    def _receive(self, operation: str):
        ready = multiprocessing.connection.wait(
            (self._connection, self._process.sentinel),
            timeout=self._TIMEOUT_SECONDS,
        )
        if self._connection in ready:
            try:
                status, value = self._connection.recv()
            except EOFError as error:
                self._process.join(timeout=1)
                raise NativeEngineCrash(operation, self._process.exitcode) from error
            if status == "ready" or status == "ok":
                return value
            if status == "error":
                raise RuntimeError(f"native engine worker {operation} failed: {value}")
            raise RuntimeError(f"invalid native engine worker response: {status!r}")
        if self._process.sentinel in ready:
            self._process.join(timeout=1)
            raise NativeEngineCrash(operation, self._process.exitcode)
        raise RuntimeError(
            f"native engine worker timed out during {operation} after "
            f"{self._TIMEOUT_SECONDS:g}s"
        )


def _build_init(
    specs: tuple[TeamSpec, TeamSpec], seed: tuple[int, int, int, int],
) -> BattleInit:
    init = BattleInit()
    init.abi_version = ABI_VERSION
    init.struct_size = ctypes.sizeof(BattleInit)
    for side, spec in enumerate(specs):
        payload = spec.battle_team()
        pokemon = payload["pokemon"]
        if len(pokemon) != TEAM_SIZE:
            raise ValueError("native team must contain exactly six Pokemon")
        init.teams[side].abi_version = ABI_VERSION
        init.teams[side].struct_size = ctypes.sizeof(BattleTeam)
        for slot, value in enumerate(pokemon):
            init.teams[side].pokemon[slot] = _build_set(value)
    for index, value in enumerate(seed):
        init.seed[index] = _uint(value, 0xFFFF, "Showdown seed word")
    return init


def write_battle_init(
    specs: tuple[TeamSpec, TeamSpec], seed: tuple[int, int, int, int], path: Path,
) -> None:
    """Write the exact validated host-ABI payload consumed by the Ocean env."""
    init = _build_init(specs, seed)
    path.write_bytes(bytes(init))


def _build_set(value: dict[str, object]) -> PokemonSet:
    result = PokemonSet()
    result.abi_version = ABI_VERSION
    result.struct_size = ctypes.sizeof(PokemonSet)
    result.species_id = _uint(value["species_id"], 0xFFFF, "species_id")
    result.item_id = _uint(value["item_id"], 0xFFFF, "item_id")
    result.ability_id = _uint(value["ability_id"], 0xFFFF, "ability_id")
    move_ids = value["move_ids"]
    if len(move_ids) != MOVE_SLOTS:
        raise ValueError("move_ids must contain exactly four slots")
    for index, move_id in enumerate(move_ids):
        result.move_ids[index] = _uint(move_id, 0xFFFF, "move_id")
    stats = value["stats"]
    for index, name in enumerate(STAT_NAMES):
        result.stats[index] = _uint(stats[name], 0xFFFF, f"stat {name}")
    max_pp = value["move_max_pp"]
    if len(max_pp) != MOVE_SLOTS:
        raise ValueError("move_max_pp must contain exactly four slots")
    for index, pp in enumerate(max_pp):
        result.max_pp[index] = _uint(pp, 0xFFFF, "max_pp")
    result.level = _uint(value["level"], 0xFF, "level")
    result.gender = {"": 0, "N": 0, "M": 1, "F": 2}[value["gender"]]
    result.happiness = _uint(value["happiness"], 0xFF, "happiness")
    if not isinstance(value["shiny"], bool):
        raise ValueError("shiny must be boolean")
    result.shiny = value["shiny"]
    return result


def _uint(value: object, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not 0 <= value <= maximum:
        raise ValueError(f"{label} is outside 0..{maximum}")
    return value


def _actions_from_mask(mask: int) -> tuple[int, ...]:
    return tuple(action for action in range(9) if mask & (1 << action))


def _snapshot_json(snapshot: BattleSnapshot) -> dict[str, object]:
    sides = []
    for side in range(SIDE_COUNT):
        pokemon = []
        for slot in range(TEAM_SIZE):
            value = snapshot.pokemon[side][slot]
            pokemon.append({
                "set": {
                    "species_id": value.set.species_id,
                    "item_id": value.set.item_id,
                    "ability_id": value.set.ability_id,
                    "move_ids": list(value.set.move_ids),
                    "stats": list(value.set.stats),
                    "max_pp": list(value.set.max_pp),
                    "level": value.set.level,
                    "gender": value.set.gender,
                    "happiness": value.set.happiness,
                    "shiny": value.set.shiny,
                },
                "species_id": value.set.species_id,
                "hp": value.hp,
                "pp": list(value.pp),
                "status": value.status,
                "protect_counter": value.protect_counter,
                "toxic_counter": value.toxic_counter,
                "leech_seeded": value.leech_seeded,
                "stat_stages": list(value.stat_stages),
            })
        sides.append(pokemon)
    return {
        "turn": snapshot.turn,
        "force_switch_side": snapshot.force_switch_side,
        "resume_residuals": snapshot.resume_residuals,
        "done": snapshot.done,
        "winner_side": snapshot.winner_side,
        "spikes": list(snapshot.spikes),
        "seed": list(snapshot.seed),
        "sides": sides,
        "events": [
            {
                "kind": snapshot.events[index].kind,
                "side": snapshot.events[index].side,
                "status": snapshot.events[index].status,
                "species_id": snapshot.events[index].species_id,
                "move_id": snapshot.events[index].move_id,
                "hp": snapshot.events[index].hp,
                "max_hp": snapshot.events[index].max_hp,
            }
            | ({"amount": snapshot.events[index].amount}
               if snapshot.events[index].kind in (12, 13) else {})
            for index in range(snapshot.event_count)
        ],
    }
