"""Read the config files (company, metrics, source hashes) into one LoadContext.

Config problems raise ConfigError straight away: a broken config should never
produce a half-built database.
"""
import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from erp.periods import PeriodError, resolve_period

REPO = Path(__file__).resolve().parents[2]
METRICS_CONFIG = REPO / "config" / "metrics.yaml"
HASHES_FILE = REPO / "sources_hashes.txt"

METRIC_FIELDS = ("display_name", "statement", "unit_kind", "canonical_unit", "is_flow", "definition")
METRIC_SIGNS = ("outflow_positive",)   # optional metric field `sign`
ACCOUNTING_STANDARDS = ("Ind AS", "IFRS")


class ConfigError(ValueError):
    pass


@dataclass
class LoadContext:
    company: dict          # one row for the `company` table
    metrics: dict          # metric_id -> metric row
    periods: dict          # label ('FY26') -> period row with real dates
    sources: dict          # file_name -> source_document row (incl. sha256, local_path)
    bands: dict            # metric_id -> {'min': .., 'max': ..} in canonical unit
    reporting_rounding: dict = None        # reported unit -> printing step, in that unit
    primary_accounting_standard: str = None  # standard used by lookups unless told otherwise
    cross_foot_checks: list = None         # identities checked at load time (erp/db/crossfoot.py)


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


def _check_source_standard(name: str, s: dict) -> None:
    whole, by_page = s.get("accounting_standard"), s.get("accounting_standard_by_page")
    if (whole is None) == (by_page is None):
        raise ConfigError(f"source {name!r}: give exactly one of accounting_standard / accounting_standard_by_page")
    standards = [whole] if whole is not None else list(by_page)
    for std in standards:
        if std not in ACCOUNTING_STANDARDS:
            raise ConfigError(f"source {name!r}: accounting standard {std!r} is not one of {ACCOUNTING_STANDARDS}")
    if by_page is not None:
        seen = {}
        for std, pages in by_page.items():
            for page in pages:
                if page in seen:
                    raise ConfigError(f"source {name!r}: page {page} listed as both {seen[page]} and {std}")
                seen[page] = std


def _check_cross_foot_config(checks: list, metrics: dict) -> list:
    """Each identity: a name, a total metric and at least one part {metric, sign: 1 or -1}."""
    for c in checks:
        name = c.get("name")
        parts = c.get("parts") or []
        if not name or not c.get("total") or not parts:
            raise ConfigError(f"cross_foot_checks: each check needs name, total and parts, got {c!r}")
        for metric_id in [c["total"], *(p.get("metric") for p in parts)]:
            if metric_id not in metrics:
                raise ConfigError(f"cross_foot_checks {name!r}: {metric_id!r} is not a metric in metrics.yaml")
        for p in parts:
            if p.get("sign") not in (1, -1):
                raise ConfigError(f"cross_foot_checks {name!r}: sign of {p['metric']!r} must be 1 or -1")
    return checks


def accounting_standard_for(source: dict, page: int) -> str | None:
    """Accounting standard of one page of a source document, or None if not configured."""
    if source.get("accounting_standard") is not None:
        return source["accounting_standard"]
    for std, pages in (source.get("accounting_standard_by_page") or {}).items():
        if page in pages:
            return std
    return None


def _check_periods(periods: list, fiscal_year_end_month: int) -> dict:
    """Each configured period must match what the period resolver says its label means."""
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
        try:
            expected = resolve_period(p["label"], fiscal_year_end_month)
        except PeriodError as e:
            raise ConfigError(f"period {p['label']!r}: {e}") from None
        actual = (p.get("period_type"), p.get("fiscal_year"), start, end)
        wanted = (expected.period_type, expected.fiscal_year, expected.start_date, expected.end_date)
        if actual != wanted:
            raise ConfigError(
                f"period {p['label']!r}: config has type/year/dates {actual}, "
                f"but the label means {wanted}"
            )
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
        if "sign" in m and m["sign"] not in METRIC_SIGNS:
            raise ConfigError(f"metric {metric_id!r}: sign {m['sign']!r} is not one of {METRIC_SIGNS}")

    bands = cfg.get("plausibility_bands", {})
    no_band = sorted(set(metrics) - set(bands))
    if no_band:
        raise ConfigError(f"no plausibility band configured for metrics: {no_band}")

    rounding = cfg.get("reporting_rounding")
    if not rounding:
        raise ConfigError("company config has no reporting_rounding (printing step per reported unit)")
    standard = cfg.get("primary_accounting_standard")
    if standard not in ACCOUNTING_STANDARDS:
        raise ConfigError(f"primary_accounting_standard must be one of {ACCOUNTING_STANDARDS}, got {standard!r}")

    cross_foot_checks = _check_cross_foot_config(cfg.get("cross_foot_checks") or [], metrics)

    fy_end = cfg["company"]["fiscal_year_end_month"]
    hashes = read_source_hashes(hashes_file)
    sources = {}
    for s in cfg["sources"]:
        name = s["file_name"]
        _check_source_standard(name, s)
        try:
            resolve_period(s.get("period_covered"), fy_end)
        except PeriodError as e:
            raise ConfigError(f"source {name!r}: period_covered: {e}") from None
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
        periods=_check_periods(cfg["periods"], fy_end),
        sources=sources,
        bands=bands,
        reporting_rounding=rounding,
        primary_accounting_standard=standard,
        cross_foot_checks=cross_foot_checks,
    )


def company_context(ticker: str) -> LoadContext:
    """The LoadContext for one company from the default config files (config/companies/<ticker>.yaml)."""
    path = REPO / "config" / "companies" / f"{ticker.lower()}.yaml"
    if not path.exists():
        raise ConfigError(f"no company config for ticker {ticker!r} ({path})")
    return load_context(path, METRICS_CONFIG, HASHES_FILE, raw_dir=None)
