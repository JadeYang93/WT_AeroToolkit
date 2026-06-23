"""Load inputs for the standalone shape output module."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .models import AirfoilProfileSet, ShapeOutputInput


def load_config(path: str | Path) -> dict:
    """Load BAD configuration as key/value pairs."""

    config = {}
    with _open_text(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("*") or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            key = parts[0].strip()
            raw = parts[1].strip()
            try:
                value = float(raw)
                value = int(value) if value == int(value) else value
            except ValueError:
                value = raw
            config[key] = value
    return config


def read_geo(path: str | Path) -> np.ndarray:
    """Read a BAD .geo file.

    GEO 文件必须包含 7 列：``span, chord, twist, thickness, pitchaxis, prebend, sweep``
    （前 6 列单位同既有约定；第 7 列 sweep 单位 m）。
    任一数据空缺 / 缺列 / 行不齐 / 非数字都会抛 ValueError，并精确指明
    "文件第 N 行 + 哪一列"。

    文件格式（tab 或空格分隔，前两行为表头）::

        展长  弦长  扭角  相对厚度  变桨轴  预弯  后掠
        m     m     deg   %         %       m     m
        0     4.67  21    100       50      0     0
        ...
    """

    path = Path(path)
    col_names = [
        "展长(span)", "弦长(chord)", "扭角(twist)", "相对厚度(thickness)",
        "变桨轴(pitchaxis)", "预弯(prebend)", "后掠(sweep)",
    ]
    required = 7

    with _open_text(path) as f:
        lines = f.readlines()

    if len(lines) < 3:
        raise ValueError(
            f"GEO 文件至少需要 2 行表头 + 1 行数据，当前只有 {len(lines)} 行：\n  {path}"
        )

    parsed: list[list[float]] = []
    for i, raw in enumerate(lines[2:]):
        line = raw.strip()
        if not line:
            continue  # 跳过完全空行
        # 兼容 tab / 逗号 / 多空格分隔
        fields = [s.strip() for s in line.replace("\t", " ").replace(",", " ").split() if s.strip() != ""]
        file_row = i + 3  # 数据从文件第 3 行开始
        if len(fields) < required:
            raise ValueError(
                f"GEO 文件第 {file_row} 行只有 {len(fields)} 列，需要 {required} 列"
                f"（{', '.join(col_names)}）。\n  内容：{line!r}\n  文件：{path}"
            )
        row: list[float] = []
        for j, field in enumerate(fields[:required]):
            if field == "" or field.lower() in {"nan", "none", "null", "-"}:
                raise ValueError(
                    f"GEO 文件第 {file_row} 行（数据第 {i + 1} 行）"
                    f"{col_names[j]} 列空缺：\n  内容：{line!r}\n  文件：{path}"
                )
            try:
                row.append(float(field))
            except ValueError:
                raise ValueError(
                    f"GEO 文件第 {file_row} 行（数据第 {i + 1} 行）"
                    f"{col_names[j]} 列无法解析为数字：{field!r}\n  文件：{path}"
                ) from None
        parsed.append(row)

    if not parsed:
        raise ValueError(f"GEO 文件没有有效数据行：\n  {path}")

    return np.asarray(parsed, dtype=float)


def read_prof(path: str | Path) -> tuple[float, np.ndarray]:
    """Read an airfoil .prof file as ``(thickness, xy_coordinates)``."""

    with _open_text(path) as f:
        header = f.readline().strip().split()
        thickness = float(header[1]) if len(header) >= 2 else 100.0
        coords = np.loadtxt(f)
    return thickness, np.atleast_2d(np.asarray(coords, dtype=float))


def _open_text(path: str | Path):
    path = Path(path)
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return path.open("r", encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    return path.open("r", encoding="utf-8")


def _numeric_sort_key(path: Path) -> int:
    match = re.search(r"\d+", path.stem)
    return int(match.group(0)) if match else 0


def _resample_closed_profile(common_x: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Resample a closed airfoil profile by upper/lower surfaces separately."""

    lead_idx = int(np.argmin(x))
    upper_x = x[: lead_idx + 1]
    upper_y = y[: lead_idx + 1]
    lower_x = x[lead_idx:]
    lower_y = y[lead_idx:]

    upper_target = common_x[: lead_idx + 1]
    lower_target = common_x[lead_idx:]

    # np.interp requires ascending x.
    upper = np.interp(upper_target[::-1], upper_x[::-1], upper_y[::-1])[::-1]
    lower = np.interp(lower_target, lower_x, lower_y)
    return np.concatenate([upper[:-1], lower])


def load_airfoil_profiles(profile_dir: str | Path) -> AirfoilProfileSet:
    """Load a standard airfoil coordinate family from ``f*.prof`` files."""

    profile_dir = Path(profile_dir)
    files = sorted(profile_dir.glob("*.prof"), key=_numeric_sort_key)
    if not files:
        raise FileNotFoundError(f"No .prof files found in: {profile_dir}")

    thickness_values: list[float] = []
    y_columns: list[np.ndarray] = []
    common_x: np.ndarray | None = None

    for path in files:
        thickness, coords = read_prof(str(path))
        coords = np.asarray(coords, dtype=float)
        if coords.shape[1] < 2:
            raise ValueError(f"Invalid profile file: {path}")
        x = coords[:, 0]
        y = coords[:, 1]
        if common_x is None:
            common_x = x
            y_columns.append(y)
        # MATLAB assumes the profile family already shares one x grid.
        # Some files differ only by tiny roundoff (about 1e-6), and treating
        # them as a different grid would force a bad np.interp on a non-
        # monotonic closed airfoil coordinate sequence.
        elif len(x) == len(common_x) and np.allclose(x, common_x, atol=1e-5, rtol=1e-8):
            y_columns.append(y)
        else:
            y_columns.append(_resample_closed_profile(common_x, x, y))
        thickness_values.append(float(thickness))

    return AirfoilProfileSet(
        x=np.asarray(common_x, dtype=float),
        y=np.column_stack(y_columns),
        thickness=np.asarray(thickness_values, dtype=float),
        source_dir=profile_dir,
    )


def resolve_profile_family(appdata: str | Path, family: str | None = None) -> str:
    """Resolve the airfoil coordinate family from configuration or name."""

    appdata = Path(appdata)
    root = appdata / "Aerofoil_coordinate"
    families = sorted([p.name for p in root.iterdir() if p.is_dir()]) if root.exists() else []
    if not families:
        raise FileNotFoundError(f"No airfoil coordinate families found in: {root}")
    if family:
        if family not in families:
            raise FileNotFoundError(f"Unknown profile family {family!r}; available: {families}")
        return family

    cfg_path = appdata / "Initialization" / "configuration.txt"
    cfg = load_config(str(cfg_path)) if cfg_path.exists() else {}
    idx = max(int(cfg.get("POP_foilProf_database", 1)) - 1, 0)
    return families[min(idx, len(families) - 1)]


def load_sections(path: str | Path) -> np.ndarray:
    """Load output section positions from a one-column text file."""

    return _load_numeric_table(path, skip_header=1).reshape(-1)


def load_tail_table(path: str | Path) -> np.ndarray:
    """Load relative trailing-edge-thickness correction table."""

    return _load_numeric_table(path, skip_header=2)


def _load_numeric_table(path: str | Path, skip_header: int) -> np.ndarray:
    path = Path(path)
    last_error: Exception | None = None
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            with path.open("r", encoding=encoding) as f:
                for _ in range(skip_header):
                    f.readline()
                data = np.loadtxt(f)
            return np.atleast_2d(np.asarray(data, dtype=float))
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise ValueError(f"Could not read numeric table: {path}")


def load_shape_output_input(
    appdata: str | Path,
    geo_path: str | Path,
    profile_family: str | None = None,
    section_path: str | Path | None = None,
    tail_path: str | Path | None = None,
) -> ShapeOutputInput:
    """Build a complete module input from existing BAD AppData files."""

    appdata = Path(appdata)
    family = resolve_profile_family(appdata, profile_family)
    profiles = load_airfoil_profiles(appdata / "Aerofoil_coordinate" / family)
    # Initialization/section.txt 与 tail_correct.txt 是可选输入：
    # 当前 UI 流程不依赖它们（use_original_sections=True 用 geo 第一列；
    # tail_table 在 compute.py 里未被消费）。找不到文件时设 None 让 compute.py
    # 自然走 fallback 路径，不再强制要求 Initialization/ 存在。
    sec_path = section_path or (appdata / "Initialization" / "section.txt")
    tail_path_resolved = tail_path or (appdata / "Initialization" / "tail_correct.txt")
    sections = load_sections(sec_path) if Path(sec_path).exists() else None
    tail_table = load_tail_table(tail_path_resolved) if Path(tail_path_resolved).exists() else None
    return ShapeOutputInput(
        geo=read_geo(str(geo_path)),
        profiles=profiles,
        sections=sections,
        tail_table=tail_table,
    )
