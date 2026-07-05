from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from thaum_nexus.data_model import BoardState, Cell, CellKind, HexCoord
from thaum_nexus.knowledge_base import KnowledgeBase

from .aspect_matcher import AspectMatch, AspectMatcher, Image, _foreground_mask_descriptor
from .calibration import CalibrationProfile
from .hex_detector import HexPresence, HexPresenceDetector
from .hex_geometry import DEFAULT_GRID_GEOMETRY, HexGridGeometry


class BoardReadError(RuntimeError):
    """Raised when screenshot-to-board conversion cannot produce a valid board."""


@dataclass(frozen=True)
class CellRead:
    coord: HexCoord
    crop_box: tuple[int, int, int, int]
    match: AspectMatch | None

    @property
    def aspect(self) -> str | None:
        return self.match.key if self.match else None

    @property
    def score(self) -> float | None:
        return self.match.score if self.match else None


@dataclass(frozen=True)
class BoardReadResult:
    board: BoardState
    reads: dict[HexCoord, CellRead]
    presence: dict[HexCoord, HexPresence] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BoardReadConfig:
    """Configuration for converting a calibrated screenshot into BoardState."""

    coords: tuple[HexCoord, ...]
    root_coords: frozenset[HexCoord] = frozenset()
    match_threshold: float = 0.82
    crop_radius: float = 32.0
    strict_roots: bool = True

    @classmethod
    def from_iterables(
        cls,
        coords: Iterable[HexCoord],
        *,
        root_coords: Iterable[HexCoord] = (),
        match_threshold: float = 0.82,
        crop_radius: float = 32.0,
        strict_roots: bool = True,
    ) -> "BoardReadConfig":
        return cls(
            coords=tuple(sorted(set(coords))),
            root_coords=frozenset(root_coords),
            match_threshold=match_threshold,
            crop_radius=crop_radius,
            strict_roots=strict_roots,
        )


@dataclass(frozen=True)
class AutoBoardReadConfig:
    """Configuration for detecting actual cells before reading aspects."""

    search_coords: tuple[HexCoord, ...] = ()
    root_coords: frozenset[HexCoord] = frozenset()
    match_threshold: float = 0.82
    icon_crop_radius: float = 9.0
    presence_crop_radius: float = 9.0
    candidate_margin: float = 30.0
    strict_roots: bool = True
    auto_roots: bool = True
    icon_presence_threshold: float = 0.30

    @classmethod
    def from_iterables(
        cls,
        *,
        search_coords: Iterable[HexCoord] = (),
        root_coords: Iterable[HexCoord] = (),
        match_threshold: float = 0.82,
        icon_crop_radius: float = 9.0,
        presence_crop_radius: float = 9.0,
        candidate_margin: float = 30.0,
        strict_roots: bool = True,
        auto_roots: bool = True,
        icon_presence_threshold: float = 0.30,
    ) -> "AutoBoardReadConfig":
        return cls(
            search_coords=tuple(sorted(set(search_coords))),
            root_coords=frozenset(root_coords),
            match_threshold=match_threshold,
            icon_crop_radius=icon_crop_radius,
            presence_crop_radius=presence_crop_radius,
            candidate_margin=candidate_margin,
            strict_roots=strict_roots,
            auto_roots=auto_roots,
            icon_presence_threshold=icon_presence_threshold,
        )


class BoardReader:
    """Read a research-note BoardState from a calibrated screenshot.

    Initial version intentionally accepts explicit candidate coords and root
    coord hints. Automatic detection of existing/missing hex cells and root
    backgrounds can be layered on top later without changing solver inputs.
    """

    def __init__(
        self,
        kb: KnowledgeBase,
        matcher: AspectMatcher,
        *,
        geometry: HexGridGeometry = DEFAULT_GRID_GEOMETRY,
    ) -> None:
        self.kb = kb
        self.matcher = matcher
        self.geometry = geometry

    def read(
        self,
        screenshot,
        calibration: CalibrationProfile,
        config: BoardReadConfig,
        *,
        name: str = "",
    ) -> BoardReadResult:
        if Image is None:
            raise BoardReadError("Pillow is required for BoardReader")
        if screenshot.mode != "RGBA":
            screenshot = screenshot.convert("RGBA")

        cells: list[Cell] = []
        reads: dict[HexCoord, CellRead] = {}
        warnings: list[str] = []

        for coord in config.coords:
            crop_box = self.geometry.screen_crop_box(coord, calibration, radius=config.crop_radius)
            match = self.matcher.match_crop(screenshot, crop_box, threshold=config.match_threshold)
            reads[coord] = CellRead(coord=coord, crop_box=crop_box, match=match)

            if match is not None:
                self.kb.require_aspect(match.key)
                kind = CellKind.ROOT if coord in config.root_coords else CellKind.PLACED
                cells.append(Cell(coord=coord, kind=kind, aspect=match.key))
                continue

            if coord in config.root_coords:
                message = f"root coord {coord.key()} did not match any aspect"
                if config.strict_roots:
                    raise BoardReadError(message)
                warnings.append(message)
            cells.append(Cell(coord=coord, kind=CellKind.EMPTY))

        return BoardReadResult(board=BoardState(cells={cell.coord: cell for cell in cells}, name=name), reads=reads, warnings=tuple(warnings))

    def read_auto(
        self,
        screenshot,
        calibration: CalibrationProfile,
        config: AutoBoardReadConfig,
        *,
        name: str = "",
        detector: HexPresenceDetector | None = None,
    ) -> BoardReadResult:
        """Detect present hex cells and aspect-bearing ROOT cells.

        When `auto_roots` is enabled, every confidently matched aspect icon is
        treated as a ROOT/fixed point. This matches Thaumcraft research notes:
        the icons already printed on the paper are the fixed anchors the player
        must connect. Manual `root_coords` remain as an override/fallback.
        """

        if Image is None:
            raise BoardReadError("Pillow is required for BoardReader")
        if screenshot.mode != "RGBA":
            screenshot = screenshot.convert("RGBA")
        detector = detector or HexPresenceDetector()
        search_coords = config.search_coords or self.geometry.candidate_coords(margin=config.candidate_margin)

        present_coords: set[HexCoord] = set()
        presence: dict[HexCoord, HexPresence] = {}
        reads: dict[HexCoord, CellRead] = {}
        auto_root_coords: set[HexCoord] = set()
        warnings: list[str] = []
        for coord in search_coords:
            crop_box = self.geometry.screen_crop_box(coord, calibration, radius=config.presence_crop_radius)
            detected = detector.detect(screenshot, crop_box)
            presence[coord] = detected
            if detected.present:
                present_coords.add(coord)

        for coord in config.root_coords:
            detected = presence.get(coord)
            if detected is not None and not detected.present:
                warnings.append(f"root coord {coord.key()} was not detected as a present hex")
            present_coords.add(coord)

        # Match aspects on detected cells plus explicit manual roots. Matching
        # every parchment coordinate is both slow and prone to false positives
        # from decorative page marks.
        for coord in sorted(set(present_coords).union(config.root_coords)):
            crop_box = self.geometry.screen_crop_box(coord, calibration, radius=config.icon_crop_radius)
            if coord not in config.root_coords and _icon_foreground_score(screenshot.crop(crop_box)) < config.icon_presence_threshold:
                continue
            match = self.matcher.match_crop(screenshot, crop_box, threshold=config.match_threshold)
            reads[coord] = CellRead(coord=coord, crop_box=crop_box, match=match)
            if match is not None and config.auto_roots:
                auto_root_coords.add(coord)
                present_coords.add(coord)

        root_coords = set(config.root_coords)
        if config.auto_roots:
            root_coords.update(auto_root_coords)

        cells: list[Cell] = []
        for coord in sorted(present_coords):
            read = reads.get(coord)
            match = read.match if read is not None else None
            if match is not None:
                self.kb.require_aspect(match.key)
                kind = CellKind.ROOT if coord in root_coords else CellKind.PLACED
                cells.append(Cell(coord=coord, kind=kind, aspect=match.key))
            else:
                if coord in root_coords:
                    message = f"root coord {coord.key()} did not match any aspect"
                    if config.strict_roots:
                        raise BoardReadError(message)
                    warnings.append(message)
                cells.append(Cell(coord=coord, kind=CellKind.EMPTY))

        result = BoardReadResult(
            board=BoardState(cells={cell.coord: cell for cell in cells}, name=name),
            reads={coord: reads[coord] for coord in sorted(present_coords) if coord in reads},
            presence=presence,
            warnings=tuple(warnings),
        )
        return BoardReadResult(
            board=result.board,
            reads=result.reads,
            presence=presence,
            warnings=result.warnings,
        )

    def read_gui_image(
        self,
        gui_image,
        config: BoardReadConfig,
        *,
        name: str = "",
    ) -> BoardReadResult:
        """Read from an image already cropped to GUI base coordinates."""

        return self.read(
            gui_image,
            CalibrationProfile(gui_left=0.0, gui_top=0.0, scale=1.0),
            config,
            name=name,
        )

    def read_gui_image_auto(
        self,
        gui_image,
        config: AutoBoardReadConfig,
        *,
        name: str = "",
        detector: HexPresenceDetector | None = None,
    ) -> BoardReadResult:
        """Auto-read from an image already cropped to GUI base coordinates."""

        return self.read_auto(
            gui_image,
            CalibrationProfile(gui_left=0.0, gui_top=0.0, scale=1.0),
            config,
            name=name,
            detector=detector,
        )


def _icon_foreground_score(crop) -> float:
    descriptor = _foreground_mask_descriptor(crop, size=64)
    center = descriptor.size / 2.0
    total = 0
    active = 0
    for y in range(descriptor.size):
        for x in range(descriptor.size):
            if ((x + 0.5 - center) ** 2 + (y + 0.5 - center) ** 2) ** 0.5 >= 19.0:
                continue
            total += 1
            if descriptor.mask[y * descriptor.size + x]:
                active += 1
    return active / total if total else 0.0
