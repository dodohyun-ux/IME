"""Observed trip scoring. Public proxies and synthetic cases are never ground truth."""
from datetime import datetime
import math
import statistics


def timestamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('Timestamp must include a timezone')
    return dt


def nonnegative(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Expected a number')
    if not math.isfinite(value) or value < 0:
        raise ValueError('Expected a finite nonnegative value')
    return value


def metrics(pairs):
    if not pairs:
        return dict(n=0, mae=None, bias=None, wape_pct=None)
    errors = [p-a for p,a in pairs]
    denominator = sum(a for _,a in pairs)
    return dict(n=len(pairs), mae=statistics.mean(abs(e) for e in errors),
                bias=statistics.mean(errors),
                wape_pct=100*sum(abs(e) for e in errors)/denominator if denominator else None)


def score_trips(records):
    """Fail closed on unmatched scopes, retrospective plans and missing provenance.

    A nonempty result is descriptive accuracy on supplied records, not certification
    or a causal improvement estimate. Evidence documents need human verification.
    """
    time_pairs, cost_pairs, excluded, seen = [], [], [], set()
    for row in records:
        if not isinstance(row, dict):
            excluded.append(dict(trip_id=None, metric='all', reason='Record must be an object'))
            continue
        key = row.get('trip_id')
        try:
            if not isinstance(key, str) or not key or key in seen:
                raise ValueError('Missing or duplicate trip_id')
            seen.add(key)
            if row.get('data_kind') != 'observed_trip':
                raise ValueError('Only observed_trip records are eligible')
            for field in ('actual_evidence', 'plan_evidence'):
                evidence = row[field]
                digest = evidence['sha256']
                if not evidence['reference'] or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('Document reference and SHA256 required')
            p, a = row['predicted'], row['actual']
            for field in ('origin_id','destination_id','vehicle_id','cargo_manifest_id'):
                if not p[field] or p[field] != a[field]:
                    raise ValueError('Unmatched '+field)
            departed = timestamp(a['departure_at'])
            if timestamp(row['plan_recorded_at']) > departed:
                raise ValueError('Plan was recorded after actual departure')
            if timestamp(row['plan_recorded_at']) > timestamp(p['departure_at']):
                raise ValueError('Plan was recorded after planned departure')
            if row.get('split') != 'evaluation':
                raise ValueError('Calibration records cannot count as evaluation')
        except (KeyError, TypeError, ValueError) as error:
            excluded.append(dict(trip_id=key, metric='all', reason=str(error)))
            continue
        try:
            if p['time_scope'] != 'departure_to_arrival' or a['time_scope'] != p['time_scope']:
                raise ValueError('Unmatched time scope')
            actual = (timestamp(a['arrival_at'])-departed).total_seconds()/60
            predicted = (timestamp(p['arrival_at'])-timestamp(p['departure_at'])).total_seconds()/60
            time_pairs.append((nonnegative(predicted),nonnegative(actual)))
        except (KeyError, TypeError, ValueError) as error:
            excluded.append(dict(trip_id=key,metric='time',reason=str(error)))
        try:
            for field in ('currency','tax_basis','cost_scope'):
                if not p[field] or p[field] != a[field]:
                    raise ValueError('Unmatched '+field)
            if p['currency'] != 'USD' or p['tax_basis'] not in ('net','gross') or p['cost_scope'] != 'round_trip_transport':
                raise ValueError('Expected USD net/gross round-trip transport only; convert with documented dated FX first')
            if a['cost_evidence_kind'] != 'paid_invoice':
                raise ValueError('Award/budget/tariff is not a paid invoice')
            cost_pairs.append((nonnegative(p['transport_cost']),nonnegative(a['transport_cost'])))
        except (KeyError, TypeError, ValueError) as error:
            excluded.append(dict(trip_id=key,metric='cost',reason=str(error)))
    return dict(input_records=len(records),time_minutes=metrics(time_pairs),cost_usd=metrics(cost_pairs),
                exclusions=excluded,field_effect_identified=False,operational_ready=False,
                verdict='no_matched_operating_records' if not time_pairs and not cost_pairs else 'descriptive_matched_sample_only')


def quantile_bin(percentages, probability):
    if len(percentages) != 14 or not 0 < probability < 1:
        raise ValueError('Expected 14 bins and an interior probability')
    values = [nonnegative(v) for v in percentages]
    # Published percentages are rounded to 0.1 (2022) or 0.01 (2025).
    if abs(sum(values)-100) > .71:
        raise ValueError('Speed distribution does not sum to approximately 100')
    total = sum(values)
    running = 0
    bounds = [(0,30)]+[(v,v+10) for v in range(30,150,10)]+[(150,None)]
    for value, bound in zip(values,bounds):
        running += value
        if running >= probability*total:
            return bound
    raise ValueError('Invalid distribution')
