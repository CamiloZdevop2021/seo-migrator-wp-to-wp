#!/usr/bin/env python3
"""
SEO Meta Extractor — Not Wood Edition
======================================
Extrae meta tags SEO del HTML público de cada URL en producción,
sin necesitar REST API ni autenticación.

¿Por qué este script?
Los meta tags de Rank Math se renderizan en el <head> de cada URL pública.
Hacer scraping del HTML es 100% confiable porque es lo que Google realmente
ve y indexa.

¿Qué extrae?
- <title>                         → meta_title (lo que se ve en SERP)
- <meta name="description">       → meta_description
- <link rel="canonical">          → canonical_url
- <meta name="robots">            → robots
- <meta property="og:title">      → og_title (Facebook)
- <meta property="og:description"> → og_description
- <meta property="og:image">      → og_image
- <meta property="og:type">       → og_type
- <meta name="twitter:title">     → twitter_title
- <meta name="twitter:card">      → twitter_card
- <script type="application/ld+json"> → schema_jsonld

USO:
    # Extraer metadata de las URLs HIGH-CRITICAL y HIGH
    python seo_meta_extractor.py \\
        --csv insumos\\url_mapping_curado.csv \\
        --priority HIGH-CRITICAL,HIGH \\
        --output insumos\\seo_metadata_complete.csv

    # Extraer TODO el mapping
    python seo_meta_extractor.py \\
        --csv insumos\\url_mapping_curado.csv \\
        --priority ALL \\
        --output insumos\\seo_metadata_complete.csv
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin
from datetime import datetime

import requests
from bs4 import BeautifulSoup


# ============================================================================
# CONFIGURACIÓN
# ============================================================================

SITE_ORIGEN = "https://www.not-wood.cl"
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (Migrator-Co-SEO-Extractor/1.0)"
DELAY_BETWEEN_REQUESTS = 0.5  # segundos, para no saturar el servidor


# ============================================================================
# UTILIDADES
# ============================================================================
def build_full_url(source_path: str) -> str:
    """Convierte /accesorios → https://www.not-wood.cl/accesorios"""
    if source_path.startswith('http'):
        return source_path
    return urljoin(SITE_ORIGEN, source_path)


def safe_get_content(tag) -> str:
    """Extrae content de un meta tag, manejando None."""
    if not tag:
        return ''
    if tag.name == 'meta':
        return tag.get('content', '').strip()
    if tag.name == 'link':
        return tag.get('href', '').strip()
    return tag.get_text(strip=True)


def detect_rank_math(soup: BeautifulSoup) -> bool:
    """Detecta si la página fue procesada por Rank Math."""
    # Rank Math agrega comentarios HTML específicos
    comments = soup.find_all(string=lambda text: isinstance(text, str))
    for c in comments:
        if 'Rank Math' in str(c) or 'rank-math' in str(c).lower():
            return True
    # También deja meta tags específicos
    if soup.find('meta', attrs={'name': 'generator', 'content': lambda x: x and 'Rank Math' in x}):
        return True
    return False


# ============================================================================
# EXTRACCIÓN
# ============================================================================
def extract_seo_from_url(url: str) -> dict:
    """Descarga URL y extrae todos los meta tags SEO."""
    result = {
        'url': url,
        'status': 'PENDING',
        'fetch_status_code': 0,
        'meta_title': '',
        'meta_description': '',
        'canonical_url': '',
        'robots': '',
        'og_title': '',
        'og_description': '',
        'og_image': '',
        'og_type': '',
        'twitter_title': '',
        'twitter_card': '',
        'twitter_image': '',
        'schema_jsonld_count': 0,
        'schema_types': '',
        'rank_math_detected': False,
        'h1_text': '',
        'error': '',
    }

    try:
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={'User-Agent': USER_AGENT},
            allow_redirects=True,
        )
        result['fetch_status_code'] = r.status_code

        if r.status_code != 200:
            result['status'] = 'ERROR'
            result['error'] = f'HTTP {r.status_code}'
            return result

        soup = BeautifulSoup(r.text, 'html.parser')

        # ===== TITLE =====
        title_tag = soup.find('title')
        result['meta_title'] = title_tag.get_text(strip=True) if title_tag else ''

        # ===== META DESCRIPTION =====
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        result['meta_description'] = safe_get_content(desc_tag)

        # ===== CANONICAL =====
        canonical_tag = soup.find('link', attrs={'rel': 'canonical'})
        result['canonical_url'] = safe_get_content(canonical_tag)

        # ===== ROBOTS =====
        robots_tag = soup.find('meta', attrs={'name': 'robots'})
        result['robots'] = safe_get_content(robots_tag)

        # ===== OPEN GRAPH =====
        result['og_title'] = safe_get_content(soup.find('meta', attrs={'property': 'og:title'}))
        result['og_description'] = safe_get_content(soup.find('meta', attrs={'property': 'og:description'}))
        result['og_image'] = safe_get_content(soup.find('meta', attrs={'property': 'og:image'}))
        result['og_type'] = safe_get_content(soup.find('meta', attrs={'property': 'og:type'}))

        # ===== TWITTER CARDS =====
        result['twitter_title'] = safe_get_content(soup.find('meta', attrs={'name': 'twitter:title'}))
        result['twitter_card'] = safe_get_content(soup.find('meta', attrs={'name': 'twitter:card'}))
        result['twitter_image'] = safe_get_content(soup.find('meta', attrs={'name': 'twitter:image'}))

        # ===== SCHEMA JSON-LD =====
        schema_scripts = soup.find_all('script', attrs={'type': 'application/ld+json'})
        result['schema_jsonld_count'] = len(schema_scripts)

        schema_types = set()
        for script in schema_scripts:
            try:
                data = json.loads(script.string or '{}')
                # Schema puede ser dict simple o lista
                if isinstance(data, dict):
                    if '@type' in data:
                        types = data['@type'] if isinstance(data['@type'], list) else [data['@type']]
                        schema_types.update(types)
                    if '@graph' in data:
                        for item in data['@graph']:
                            if isinstance(item, dict) and '@type' in item:
                                t = item['@type']
                                types = t if isinstance(t, list) else [t]
                                schema_types.update(types)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and '@type' in item:
                            t = item['@type']
                            types = t if isinstance(t, list) else [t]
                            schema_types.update(types)
            except (json.JSONDecodeError, AttributeError):
                continue

        result['schema_types'] = ','.join(sorted(schema_types))

        # ===== DETECTAR RANK MATH =====
        result['rank_math_detected'] = detect_rank_math(soup)

        # ===== H1 (para validación) =====
        h1_tag = soup.find('h1')
        result['h1_text'] = h1_tag.get_text(strip=True) if h1_tag else ''

        result['status'] = 'OK'

    except requests.Timeout:
        result['status'] = 'ERROR'
        result['error'] = 'Timeout (>30s)'
    except requests.RequestException as e:
        result['status'] = 'ERROR'
        result['error'] = f'Request error: {e}'
    except Exception as e:
        result['status'] = 'ERROR'
        result['error'] = f'Unexpected error: {e}'

    return result


# ============================================================================
# CARGA DEL CSV DE MAPPING
# ============================================================================
def load_mapping(csv_path: str, priorities: list) -> list:
    """Carga el CSV de mapping curado y filtra por prioridades."""
    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): (v.strip() if v else '') for k, v in row.items()}
            priority = row.get('priority', '').upper()

            if 'ALL' in priorities or priority in priorities:
                rows.append(row)

    return rows


# ============================================================================
# REPORTE
# ============================================================================
def save_results(results: list, output_path: Path):
    """Guarda los resultados en CSV."""
    fieldnames = [
        'source_path',
        'priority',
        'url',
        'status',
        'fetch_status_code',
        'meta_title',
        'meta_description',
        'canonical_url',
        'robots',
        'og_title',
        'og_description',
        'og_image',
        'og_type',
        'twitter_title',
        'twitter_card',
        'twitter_image',
        'schema_jsonld_count',
        'schema_types',
        'rank_math_detected',
        'h1_text',
        'error',
    ]

    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)


def print_summary(results: list):
    """Imprime resumen en consola."""
    total = len(results)
    ok = sum(1 for r in results if r.get('status') == 'OK')
    err = sum(1 for r in results if r.get('status') == 'ERROR')

    rank_math = sum(1 for r in results if r.get('rank_math_detected'))
    with_title = sum(1 for r in results if r.get('meta_title'))
    with_desc = sum(1 for r in results if r.get('meta_description'))
    with_og = sum(1 for r in results if r.get('og_title'))
    with_schema = sum(1 for r in results if r.get('schema_jsonld_count', 0) > 0)

    print(f"\n{'='*65}")
    print(f"📊 RESUMEN DE EXTRACCIÓN")
    print(f"{'='*65}")
    print(f"   Total URLs procesadas:      {total}")
    print(f"   ✅ OK:                       {ok}")
    print(f"   ❌ ERROR:                    {err}")
    print(f"")
    print(f"   Rank Math detectado:        {rank_math}/{total}")
    print(f"   Con meta title:             {with_title}/{total}")
    print(f"   Con meta description:       {with_desc}/{total}")
    print(f"   Con Open Graph:             {with_og}/{total}")
    print(f"   Con Schema JSON-LD:         {with_schema}/{total}")
    print(f"{'='*65}\n")


# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='SEO Meta Extractor — Not Wood')
    parser.add_argument('--csv', required=True,
                        help='Path al CSV de mapping curado')
    parser.add_argument('--priority', default='HIGH-CRITICAL,HIGH',
                        help='Prioridades a procesar separadas por coma (default: HIGH-CRITICAL,HIGH)')
    parser.add_argument('--output', default='insumos/seo_metadata_complete.csv',
                        help='CSV de salida')
    parser.add_argument('--delay', type=float, default=DELAY_BETWEEN_REQUESTS,
                        help='Delay entre requests en segundos (default: 0.5)')
    args = parser.parse_args()

    # Validar archivo
    if not Path(args.csv).exists():
        print(f"❌ No se encontró: {args.csv}")
        sys.exit(1)

    # Parsear prioridades
    priorities = [p.strip().upper() for p in args.priority.split(',')]

    # Cargar mapping
    rows = load_mapping(args.csv, priorities)

    if not rows:
        print(f"❌ No se encontraron URLs con prioridad {priorities} en {args.csv}")
        sys.exit(1)

    print(f"\n📋 Configuración:")
    print(f"   CSV input:    {args.csv}")
    print(f"   Prioridades:  {priorities}")
    print(f"   URLs a procesar: {len(rows)}")
    print(f"   Output:       {args.output}")
    print(f"   Delay:        {args.delay}s entre requests")
    print()

    # Procesar
    results = []
    for i, row in enumerate(rows, 1):
        source_path = row.get('source_path', '')
        priority = row.get('priority', 'UNKNOWN')
        url = row.get('url_full', '') or build_full_url(source_path)

        print(f"[{i}/{len(rows)}] [{priority}] {source_path}", end=' ... ', flush=True)

        extraction = extract_seo_from_url(url)
        result = {
            'source_path': source_path,
            'priority': priority,
            **extraction,
        }
        results.append(result)

        # Output amigable
        if extraction['status'] == 'OK':
            indicators = []
            if extraction['meta_title']:
                indicators.append('T')
            if extraction['meta_description']:
                indicators.append('D')
            if extraction['canonical_url']:
                indicators.append('C')
            if extraction['og_title']:
                indicators.append('OG')
            if extraction['schema_jsonld_count'] > 0:
                indicators.append(f'S({extraction["schema_jsonld_count"]})')
            print(f"✅ [{','.join(indicators)}]")
        else:
            print(f"❌ {extraction.get('error', 'unknown')}")

        # Rate limiting
        if i < len(rows):
            time.sleep(args.delay)

    # Guardar
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_results(results, output_path)

    # Summary
    print_summary(results)
    print(f"📄 CSV guardado en: {output_path}")
    print()


if __name__ == '__main__':
    main()
    