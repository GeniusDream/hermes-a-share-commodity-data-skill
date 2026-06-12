#!/usr/bin/env python3
"""Commodity signal ranking for A-share raw-material reports.

The ranking objective is upstream raw-material price-signal discovery.  It should
find clear commodity moves first; A-share board feedback and chain validation are
handled by later report layers.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Optional, Sequence

from a_share_commodity_universe import family_for, is_core_name, is_expanded_name


HIGH_RESEARCH_FAMILIES = {'黑色', '有色', '能源化工', '建材光伏', '新能源材料'}
MEDIUM_RESEARCH_FAMILIES = {'农化', '橡胶'}
LOWER_RESEARCH_FAMILIES = {'贵金属', '农产品'}


def _num(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return default
        return out
    except Exception:
        return default


def _first_num(move: Mapping, keys: Sequence[str], default: float = 0.0) -> float:
    for key in keys:
        if key in move and move.get(key) is not None:
            return _num(move.get(key), default)
    return default


def window_return(move: Mapping) -> float:
    """Directional window return in percent, using canonical key aliases."""
    return _first_num(move, ('window_chg', 'pct_chg', 'night_chg', 'chg_open', 'day_chg'), 0.0)


def window_amplitude(move: Mapping) -> float:
    return _first_num(move, ('window_amp', 'amplitude', 'night_amp', 'amp', 'day_amp'), 0.0)


def close_position(move: Mapping) -> Optional[float]:
    """Return close location in [0, 1] when high/low/end are known.

    1 means close is at the high of the window; 0 means close is at the low.
    """
    if move.get('close_position') is not None:
        return max(0.0, min(1.0, _num(move.get('close_position'), 0.5)))
    high = _first_num(move, ('high_price', 'high'), None)
    low = _first_num(move, ('low_price', 'low'), None)
    end = _first_num(move, ('end_price', 'night_close', 'last', 'close'), None)
    try:
        if high is None or low is None or end is None or high <= low:
            return None
        return max(0.0, min(1.0, (end - low) / (high - low)))
    except Exception:
        return None


def direction_quality(move: Mapping) -> float:
    """Quality of directional signal in [0, 1].

    For up moves, closing near the high is high quality. For down moves, closing
    near the low is high quality. Flat moves are neutral. If close-location is not
    known, use a neutral score so missing fields do not dominate ranking.
    """
    ret = window_return(move)
    pos = close_position(move)
    if pos is None:
        return 0.55
    if ret > 0:
        return pos
    if ret < 0:
        return 1.0 - pos
    return 0.5


def research_weight(name: str) -> float:
    """Static commodity research value in [0, 1]."""
    name = name or ''
    if is_core_name(name):
        return 1.0
    fam = family_for(name)
    if fam in HIGH_RESEARCH_FAMILIES:
        return 0.82
    if fam in MEDIUM_RESEARCH_FAMILIES:
        return 0.68
    if fam in LOWER_RESEARCH_FAMILIES:
        return 0.52
    if is_expanded_name(name):
        return 0.60
    return 0.50


def percentile_from_history(abs_return: float, history_abs_returns: Optional[Iterable[float]]) -> Optional[float]:
    vals = sorted(_num(x, None) for x in (history_abs_returns or []))
    vals = [x for x in vals if x is not None and x >= 0]
    if len(vals) < 10:
        return None
    less_equal = sum(1 for x in vals if x <= abs_return)
    return less_equal / len(vals)


def _return_strength(abs_return: float, move: Mapping) -> float:
    """Scale directional return into [0, 1], preferring self-history when present."""
    pct = move.get('abs_return_percentile')
    if pct is None:
        pct = percentile_from_history(abs_return, move.get('history_abs_returns'))
    if pct is not None:
        pct = max(0.0, min(1.0, _num(pct, 0.0)))
        # Keep some raw-return sensitivity so a 4% move still beats a tiny but
        # statistically rare move, while percentile supplies cross-commodity normalization.
        raw_component = min(abs_return / 4.0, 1.0)
        return 0.65 * pct + 0.35 * raw_component
    return min(abs_return / 3.0, 1.0)


def commodity_signal_score(move: Mapping) -> float:
    """Score an upstream commodity move for raw-material signal discovery.

    The score intentionally does not use A-share downstream feedback.  Amplitude
    is not an additive main factor; it only penalizes noisy reversals and mildly
    rewards moves that close in the direction of travel.
    """
    name = str(move.get('name') or '')
    ret = window_return(move)
    abs_ret = abs(ret)
    amp = max(window_amplitude(move), abs_ret)
    strength = _return_strength(abs_ret, move)
    pct = move.get('abs_return_percentile')
    percentile_component = max(0.0, min(1.0, _num(pct, 0.0))) if pct is not None else strength
    quality = direction_quality(move)
    rw = research_weight(name)

    # Noise penalty: large range with little final directional move and neutral
    # close location is usually a reversal/noise event, not a stable raw-material signal.
    reversal_ratio = 0.0
    if amp > 0:
        reversal_ratio = max(0.0, min(1.0, 1.0 - abs_ret / amp))
    noise_penalty = 0.18 * reversal_ratio * (1.0 - quality)

    return (
        0.50 * strength
        + 0.20 * percentile_component
        + 0.15 * quality
        + 0.15 * rw
        - noise_penalty
    )


def material_move(move: Mapping, core_min_return: float = 0.5, expanded_min_return: float = 0.8) -> bool:
    """Whether a commodity should enter the anomaly candidate pool.

    Directional return is the gate. Amplitude alone can only pass when the move
    also closes at a directional endpoint, not when it is a full reversal.
    """
    name = str(move.get('name') or '')
    ret = abs(window_return(move))
    amp = window_amplitude(move)
    threshold = core_min_return if is_core_name(name) else expanded_min_return
    if ret >= threshold:
        return True
    if ret >= threshold * 0.65 and direction_quality(move) >= 0.75:
        return True
    if amp >= 3.0 and ret >= threshold * 0.5 and direction_quality(move) >= 0.80:
        return True
    return False


def rank_commodity_moves(
    moves: Sequence[Mapping],
    core_limit: int = 5,
    expanded_limit: int = 3,
    strong_core_limit: int = 8,
) -> list[Mapping]:
    """Rank commodity moves: core pool first, expanded radar second."""
    eligible = [x for x in moves if material_move(x)]
    core = sorted((x for x in eligible if is_core_name(str(x.get('name') or ''))), key=commodity_signal_score, reverse=True)
    expanded = sorted((x for x in eligible if not is_core_name(str(x.get('name') or ''))), key=commodity_signal_score, reverse=True)
    selected = list(core[:core_limit])
    for item in core[core_limit:]:
        if abs(window_return(item)) >= 2.0 and item not in selected:
            selected.append(item)
        if len(selected) >= strong_core_limit:
            break
    selected.extend(expanded[:expanded_limit])
    if not selected:
        return sorted(list(moves), key=commodity_signal_score, reverse=True)[:core_limit]
    return selected


def attach_history_percentiles(moves: Sequence[dict], history_by_name: Mapping[str, Sequence[float]]) -> list[dict]:
    """Return copies with abs_return_percentile populated when history is enough."""
    out = []
    for move in moves:
        copied = dict(move)
        pct = percentile_from_history(abs(window_return(copied)), history_by_name.get(str(copied.get('name') or '')))
        if pct is not None:
            copied['abs_return_percentile'] = pct
        out.append(copied)
    return out
