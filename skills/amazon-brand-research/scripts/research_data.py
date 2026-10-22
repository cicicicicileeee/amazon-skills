#!/usr/bin/env python3
"""Offline, standard-library helpers. No data acquisition or skill self-modification."""
import argparse
import csv
import datetime as dt
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMAS = {
    'sources': 'source_id,source_type,url,accessed_at,observed_period,tool_or_publisher,parameters,raw_file,coverage_limitations',
    'asin_monthly': 'marketplace,month,asin,parent_asin,entity_level,brand,title,model,brand_verified,category_name,category_name_zh,node_id,sales_scope,count_key,units,revenue,currency,data_kind,measurement_source,offer_price,list_price,regular_price,promotion_price,price_basis,availability,seller_id,seller_class,seller_identity_evidence,source_id',
    'products': 'product_id,brand,model,marketplace,asin,parent_asin,category_name,category_name_zh,node_id,entity_level,official_url,amazon_url,status,status_evidence,observed_at,source_id',
    'category_top100': 'marketplace,node_id,category_name,category_name_zh,period,rank,asin,parent_asin,count_key,sales_scope,brand,units,revenue,currency,price,ratings,rating_count,seller_class,source_id',
    'competitors': 'focal_product,competitor_product,role,selection_reason,marketplace,asin,model,price,currency,units,period,key_claims,claim_sources,review_pain_points,listing_findings,traffic_findings,source_id',
    'official_catalog': 'market,locale,model,category,configuration,colors,product_url,purchase_url,currency,offer_price,list_price,promotion_price,stock_status,stock_variant,price_conditions,observed_at,source_id',
    'complaints': 'evidence_id,experience_id,source_id,platform,evidence_set,url,canonical_url,published_at,collected_at,brand,model,language,country,country_basis,market_relevance,firsthand,promotional,complaint,issue_code,severity,excerpt,summary_zh,content_hash',
}
MARKETS = {
    'com': ('US', 'USD'), 'ca': ('CA', 'CAD'), 'com.mx': ('MX', 'MXN'),
    'com.br': ('BR', 'BRL'), 'co.uk': ('GB', 'GBP'), 'de': ('DE', 'EUR'),
    'es': ('ES', 'EUR'), 'fr': ('FR', 'EUR'), 'it': ('IT', 'EUR'),
    'nl': ('NL', 'EUR'), 'se': ('SE', 'SEK'), 'pl': ('PL', 'PLN'),
    'com.be': ('BE', 'EUR'), 'ie': ('IE', 'EUR'), 'co.jp': ('JP', 'JPY'),
    'in': ('IN', 'INR'), 'com.au': ('AU', 'AUD'), 'sg': ('SG', 'SGD'),
    'ae': ('AE', 'AED'), 'sa': ('SA', 'SAR'), 'com.tr': ('TR', 'TRY'),
    'eg': ('EG', 'EGP'), 'co.za': ('ZA', 'ZAR'),
}
ALIASES = {'us': 'com', 'uk': 'co.uk', 'gb': 'co.uk', 'jp': 'co.jp',
           'mx': 'com.mx', 'br': 'com.br', 'au': 'com.au', 'be': 'com.be',
           'tr': 'com.tr', 'za': 'co.za'}


def market(value):
    v = value.strip().lower()
    if '://' in v:
        v = urlsplit(v).hostname or ''
    v = v.removeprefix('www.').removeprefix('amazon.')
    v = ALIASES.get(v, v)
    if v not in MARKETS:
        raise ValueError('Unknown marketplace; confirm the Amazon domain and metadata.')
    country, currency = MARKETS[v]
    return 'amazon.' + v, country, currency


def window(as_of, months=12):
    day = dt.date.fromisoformat(as_of)
    if not 1 <= months <= 120:
        raise ValueError('months must be between 1 and 120')
    end = day.replace(day=1) - dt.timedelta(days=1)
    index = end.year * 12 + end.month - months
    start = dt.date(index // 12, index % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def read_csv(path, required=()):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'{Path(path).name}: missing columns {sorted(missing)}')
        return [{k: (v or '').strip() for k, v in row.items() if k} for row in reader]


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # BOM supports Chinese text when opened in common spreadsheet applications.
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def number(raw):
    if raw in ('', None):
        return None
    try:
        n = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(f'Invalid number: {raw!r}') from exc
    if not n.is_finite() or n < 0:
        raise ValueError(f'Expected finite, nonnegative number: {raw!r}')
    return n


def init_run(brand, marketplace, as_of, out, months=12):
    domain, country, currency = market(marketplace)
    start, end = window(as_of, months)
    if not brand.strip():
        raise ValueError('brand is required')
    root = Path(out)
    root.mkdir(parents=True, exist_ok=False)
    for folder in ('data', 'raw', 'report'):
        (root / folder).mkdir()
    config = dict(brand=brand.strip(), marketplace=domain, country=country,
                  currency=currency, as_of=as_of, period_start=start, period_end=end,
                  months=months, brand_aliases=[], include_subbrands=False, scope_notes=[])
    (root / 'run_config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name, header in SCHEMAS.items():
        write_csv(root / 'data' / (name + '.csv'), [], header.split(','))
    return config


def aggregate(rows):
    """Keep actual/estimate, currencies and measurements separate; reject overlap."""
    groups, primary = defaultdict(list), set()
    for r in rows:
        key = tuple(r.get(k, '') for k in ('marketplace', 'month', 'asin', 'data_kind', 'measurement_source'))
        if key in primary:
            raise ValueError(f'Duplicate monthly primary key: {key}')
        primary.add(key)
        try:
            date = dt.datetime.strptime(r['month'], '%Y-%m')
            if date.strftime('%Y-%m') != r['month']:
                raise ValueError('Use YYYY-MM')
        except (KeyError, ValueError) as exc:
            raise ValueError('Invalid monthly date') from exc
        if r.get('brand_verified') != 'true':
            continue
        if r.get('data_kind') not in ('actual', 'estimate'):
            raise ValueError('data_kind must be actual or estimate')
        if not r.get('brand') or not r.get('currency') or not r.get('asin') or not r.get('measurement_source'):
            raise ValueError('Verified monthly rows require brand, ASIN, currency and measurement_source')
        for k in ('units', 'revenue', 'offer_price', 'list_price', 'regular_price', 'promotion_price'):
            number(r.get(k))
        group = tuple(r.get(k, '') for k in ('marketplace', 'month', 'brand', 'currency', 'data_kind', 'measurement_source'))
        groups[group].append(r)
    output = []
    for key, items in sorted(groups.items()):
        counts, families = {}, defaultdict(set)
        children = {r['asin'] for r in items if r.get('entity_level') == 'child'}
        for r in items:
            scope = r.get('sales_scope')
            if scope not in ('child', 'parent'):
                continue
            if not r.get('count_key'):
                raise ValueError('Known sales_scope requires count_key')
            family = r.get('parent_asin') or (r['asin'] if scope == 'parent' else '')
            if family:
                families[family].add(scope)
            measurement = (scope, r['count_key'])
            vals = (number(r.get('units')), number(r.get('revenue')))
            if measurement in counts and counts[measurement] != vals:
                raise ValueError(f'Conflicting values for measurement {measurement}')
            counts[measurement] = vals
        if any(len(scopes) > 1 for scopes in families.values()):
            raise ValueError('Parent and child sales overlap; select one measurement basis')
        vals = list(counts.values())
        units = sum((u for u, _ in vals if u is not None), Decimal(0)) if any(u is not None for u, _ in vals) else None
        revenue = sum((v for _, v in vals if v is not None), Decimal(0)) if any(v is not None for _, v in vals) else None
        matched = [(u, v) for u, v in vals if u is not None and v is not None]
        covered = sum((u for u, _ in matched), Decimal(0)) if matched else None
        matched_rev = sum((v for _, v in matched), Decimal(0)) if matched else None
        known_availability = any(r.get('availability') in ('active', 'unavailable') for r in items if r.get('entity_level') == 'child')
        child_sales_known = any(r.get('entity_level') == 'child' and r.get('sales_scope') == 'child' and number(r.get('units')) is not None for r in items)
        active = {r['asin'] for r in items if r.get('entity_level') == 'child' and r.get('availability') == 'active'}
        selling = {r['asin'] for r in items if r.get('entity_level') == 'child' and r.get('sales_scope') == 'child' and (number(r.get('units')) or 0) > 0}
        output.append(dict(zip(('marketplace', 'month', 'brand', 'currency', 'data_kind', 'measurement_source'), key),
                           known_units=units, observed_revenue=revenue, matched_revenue=matched_rev,
                           revenue_covered_units=covered,
                           revenue_coverage=(covered or Decimal(0)) / units if units else None,
                           matched_asp=matched_rev / covered if covered else None,
                           observed_child_asins=len(children), active_child_asins=len(active) if known_availability else None,
                           availability_covered_child_asins=len({r['asin'] for r in items if r.get('entity_level') == 'child' and r.get('availability') in ('active', 'unavailable')}),
                           child_asins_with_sales=len(selling) if child_sales_known else None,
                           known_measurements=len(counts), unknown_scope_rows=sum(r.get('sales_scope') not in ('child', 'parent') for r in items)))
    return output


def canonical_url(value):
    p = urlsplit(value.strip())
    if p.scheme not in ('https', 'http') or not p.hostname:
        return ''
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    # Retain comment IDs and fragments; a video/thread page is not a unique experience.
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), p.fragment))


def precise_url(value):
    p = urlsplit(value)
    host, path = (p.hostname or ''), p.path
    query = dict(parse_qsl(p.query))
    if host.endswith('youtube.com') or host == 'youtu.be':
        return bool(query.get('lc'))
    if host.endswith('reddit.com'):
        return '/comments/' in path and len(path.strip('/').split('/')) >= 6
    if host in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'):
        return '/status/' in path
    if host.endswith('amazon.com') or 'amazon.' in host:
        return '/customer-reviews/' in path
    return False  # Unknown forum permalinks require explicit experience_id or text hash.


def complaint_analysis(rows):
    roots = list(range(len(rows)))

    def find(i):
        while roots[i] != i:
            roots[i] = roots[roots[i]]
            i = roots[i]
        return i

    lookup = {}
    for i, r in enumerate(rows):
        url = canonical_url(r.get('canonical_url') or r.get('url', ''))
        r = dict(r, canonical_url=url)
        rows[i] = r
        keys = []
        # Never deduplicate just because two excerpts or complaint themes are similar.
        for field in ('experience_id', 'content_hash'):
            if r.get(field):
                keys.append((r.get('brand', ''), r.get('model', ''), field, r[field]))
        if precise_url(url):
            keys.append((r.get('brand', ''), r.get('model', ''), 'url', url))
        for k in keys:
            if k in lookup:
                roots[find(i)] = find(lookup[k])
            lookup[k] = i
    cleaned, samples, themes = [], defaultdict(set), defaultdict(set)
    excluded = 0
    for i, r in enumerate(rows):
        reasons = []
        for field, expected in (('complaint', 'true'), ('firsthand', 'true'), ('promotional', 'false')):
            if r.get(field) != expected:
                reasons.append(field + '_not_' + expected)
        if not r.get('url') or not r.get('excerpt') or not r.get('source_id') or not r.get('published_at'):
            reasons.append('missing_original_evidence')
        if r.get('evidence_set') not in ('social', 'amazon_review'):
            reasons.append('unknown_evidence_set')
        relevance = r.get('market_relevance', 'unknown')
        if relevance == 'target' and not (r.get('country') and r.get('country_basis')):
            relevance = 'unknown'
        if relevance not in ('target', 'global', 'unknown'):
            relevance = 'unknown'
        experience = 'experience-' + str(find(i) + 1)
        row = dict(r, dedup_id=experience, normalized_relevance=relevance, exclusion_reason=';'.join(reasons))
        cleaned.append(row)
        if reasons:
            excluded += 1
            continue
        group = (r.get('evidence_set'), relevance, r.get('brand', ''), r.get('model', ''))
        samples[group].add(experience)
        if r.get('issue_code'):
            themes[group + (r['issue_code'],)].add(experience)
    summary = []
    for key, experiences in sorted(themes.items()):
        denominator = len(samples[key[:4]])
        summary.append(dict(zip(('evidence_set', 'market_relevance', 'brand', 'model', 'issue_code'), key),
                            independent_experiences=len(experiences), sample_experiences=denominator,
                            sample_theme_share=len(experiences) / denominator))
    meta = dict(input_rows=len(rows), excluded_rows=excluded,
                eligible_independent_experiences=len({r['dedup_id'] for r in cleaned if not r['exclusion_reason']}),
                note='Negative-directed sample, not defect or complaint prevalence. Do not sum product, theme, market or evidence-set groups; crossposts can appear in multiple groups.')
    return cleaned, summary, meta


def validate(root):
    root = Path(root)
    errors, warnings, counts = [], [], {}
    try:
        config = json.loads((root / 'run_config.json').read_text(encoding='utf-8'))
        start, end = dt.date.fromisoformat(config['period_start']), dt.date.fromisoformat(config['period_end'])
        if start > end or end >= dt.date.fromisoformat(config['as_of']):
            errors.append('Invalid research date range')
    except (OSError, ValueError, KeyError) as exc:
        return dict(errors=[str(exc)], warnings=[], counts={})
    tables = {}
    for name, schema in SCHEMAS.items():
        try:
            tables[name] = read_csv(root / 'data' / (name + '.csv'), schema.split(','))
            counts[name] = len(tables[name])
            if not tables[name]:
                warnings.append(name + ': no observations; disclose coverage gap')
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    sources = tables.get('sources', [])
    ids = [r['source_id'] for r in sources]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        errors.append('Source IDs must be nonempty and unique')
    for name, records in tables.items():
        if name == 'sources':
            continue
        for i, r in enumerate(records, 2):
            if not r.get('source_id') or r['source_id'] not in ids:
                errors.append(f'{name}:{i}: unresolved source_id')
            if name == 'asin_monthly':
                try:
                    month = dt.date.fromisoformat(r['month'] + '-01')
                    if not start <= month <= end:
                        errors.append(f'{name}:{i}: month outside research period')
                    if r['marketplace'] != config['marketplace']:
                        errors.append(f'{name}:{i}: wrong marketplace')
                except ValueError:
                    errors.append(f'{name}:{i}: invalid month')
            if name == 'complaints':
                for field in ('published_at', 'collected_at'):
                    try:
                        date = dt.date.fromisoformat(r[field][:10])
                        if date > dt.date.fromisoformat(config['as_of']):
                            errors.append(f'{name}:{i}: future {field}')
                    except ValueError:
                        errors.append(f'{name}:{i}: missing/invalid {field}')
                if r.get('market_relevance') == 'target' and not (r.get('country') and r.get('country_basis')):
                    warnings.append(f'{name}:{i}: target country unverified; analysis treats as unknown')
    try:
        aggregate(tables.get('asin_monthly', []))
    except (ValueError, KeyError) as exc:
        errors.append(str(exc))
    return dict(errors=errors, warnings=warnings, counts=counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('init')
    for field in ('brand', 'marketplace', 'as-of', 'out'):
        p.add_argument('--' + field, required=True)
    p.add_argument('--months', type=int, default=12)
    p = subs.add_parser('aggregate')
    p.add_argument('--input', required=True)
    p.add_argument('--out', required=True)
    p = subs.add_parser('complaints')
    p.add_argument('--input', required=True)
    p.add_argument('--out-dir', required=True)
    p = subs.add_parser('validate')
    p.add_argument('--run', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            result = init_run(args.brand, args.marketplace, args.as_of, args.out, args.months)
        elif args.command == 'aggregate':
            rows = aggregate(read_csv(args.input, SCHEMAS['asin_monthly'].split(',')))
            fields = list(rows[0]) if rows else ['marketplace', 'month', 'brand', 'currency', 'data_kind', 'measurement_source', 'known_units', 'observed_revenue', 'matched_revenue', 'revenue_covered_units', 'revenue_coverage', 'matched_asp', 'observed_child_asins', 'active_child_asins', 'availability_covered_child_asins', 'child_asins_with_sales', 'known_measurements', 'unknown_scope_rows']
            write_csv(args.out, rows, fields)
            result = dict(groups=len(rows), output=args.out)
        elif args.command == 'complaints':
            rows, summary, result = complaint_analysis(read_csv(args.input, SCHEMAS['complaints'].split(',')))
            out = Path(args.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            write_csv(out / 'coded_evidence.csv', rows, SCHEMAS['complaints'].split(',') + ['dedup_id', 'normalized_relevance', 'exclusion_reason'])
            write_csv(out / 'theme_summary.csv', summary, ['evidence_set', 'market_relevance', 'brand', 'model', 'issue_code', 'independent_experiences', 'sample_experiences', 'sample_theme_share'])
            (out / 'methodology.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        else:
            result = validate(args.run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('errors'):
            raise SystemExit(1)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
