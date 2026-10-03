"""Read the config files (company, metrics, source hashes) into one LoadContext.

Config problems raise ConfigError straight away: a broken config should never
produce a half-built database.
"""
import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

METRIC_FIELDS = ("display_name", "statement", "unit_kind", "canonical_unit", "is_flow", "definition")


class ConfigError(ValueError):
    pass


@dataclass
class LoadContext:
    company: dict          # one row for the `company` table
    metrics: dict          # metric_id -> metric row
    periods: dict          # label ('FY26') -> period row with real dates
    sources: dict          # file_name -> source_document row (incl. sha256, local_path)
    bands: dict            # metric_id -> {'min': .., 'max': ..} in canonical unit


def _read_yaml(path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def read_source_hashes(path) -> dict:
    """sources_hashes.txt (shasum format: '<sha256>  <path>') -> {file_name: sha256}."""
    hashes = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        sha, file_path = line.split(maxsplit=1)
        hashes[Path(file_path.strip()).name] = sha
    return hashes


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _check_periods(periods: list) -> dict:
    by_label = {}
    for p in periods:
        try:
            start = date.fromisoformat(p["start_date"])
            end = date.fromisoformat(p["end_date"])
        except (KeyError, TypeError, ValueError) as e:
            raise ConfigError(f"period {p.get('label')!r}: start_date/end_date must be ISO date strings ({e})")
        if start >= end:
            raise ConfigError(f"period {p['label']!r}: start_date must be before end_date")
        if p["label"] in by_label:
            raise ConfigError(f"period {p['label']!r} listed twice")
        by_label[p["label"]] = p
    return by_label


def load_context(company_config, metrics_config, hashes_file, raw_dir=None) -> LoadContext:
    """Build the LoadContext.

    raw_dir: folder holding the source PDFs (data/raw). If given, every source file
    that exists there is re-hashed and must match sources_hashes.txt. If None, the
    hash check against files is skipped (e.g. tests, or a clone without the private data).
    """
    cfg = _read_yaml(company_config)
    metrics = _read_yaml(metrics_config)["metrics"]
    for metric_id, m in metrics.items():
        missing = [k for k in METRIC_FIELDS if k not in m]
        if missing:
            raise ConfigError(f"metric {metric_id!r} missing fields: {missing}")

    bands = cfg.get("plausibility_bands", {})
    no_band = sorted(set(metrics) - set(bands))
    if no_band:
        raise ConfigError(f"no plausibility band configured for metrics: {no_band}")

    hashes = read_source_hashes(hashes_file)
    sources = {}
    for s in cfg["sources"]:
        name = s["file_name"]
        if name not in hashes:
            raise ConfigError(f"source {name!r} has no sha256 in {hashes_file}")
        row = dict(s, sha256=hashes[name], local_path=f"data/raw/{name}")
        if raw_dir is not None:
            local = Path(raw_dir) / name
            if local.exists() and _sha256_of(local) != row["sha256"]:
                raise ConfigError(f"source {name!r}: file sha256 does not match {hashes_file}")
        sources[name] = row

    return LoadContext(
        company=cfg["company"],
        metrics=metrics,
        periods=_check_periods(cfg["periods"]),
        sources=sources,
        bands=bands,
    )
