#!/usr/bin/env python3
"""
Priority Builder — Not Wood Edition
====================================
Cruza los archivos sitelinks.txt + enlaces-puntuacion-buena.txt
y genera un CSV de priorización CURADO basado en SEO real.

Lógica:
- HIGH-CRITICAL: URL en AMBOS archivos (sitelink + buena puntuación)
- HIGH:          URL solo en buena puntuación
- MEDIUM:        URL solo en sitelinks que NO sea producto individual
- LOW:           URL solo en sitelinks que SÍ sea producto individual
- FUNCIONAL:     URLs con ?filter_product, /carrito/, /tienda/, etc.

USO:
    python priority_builder.py \\
        --sitelinks sitelinks.txt \\
        --buenas enlances-puntuacion-buena.txt \\
        --output url_mapping_curado.csv
"""

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import urlparse


# ============================================================================
# CONFIGURACIÓN
# ============================================================================
SITE_DOMAIN = "www.not-wood.cl"

# Patrones para identificar URLs FUNCIONALES (no migrar manualmente)
FUNCTIONAL_PATTERNS = [
    r'\?filter_product',     # Filtros dinámicos WooCommerce
    r'/carrito/?$',          # Carrito (auto-gen)
    r'/tienda/?$',           # Tienda (auto-gen)
    r'/ofertas/?$',          # Ofertas (auto-gen si usa plugin)
    r'/categoria-revestimiento/',  # Taxonomía auto-gen
    r'/etiqueta-revestimiento/',   # Taxonomía auto-gen
]

# Patrones para identificar PÁGINAS DE CATEGORÍA/MARCA (MEDIUM)
# Si contienen estas palabras y NO son productos individuales
CATEGORY_KEYWORDS = [
    'revestimientos-', 'revestimiento-', 'perfil', 'mobiliario',
    'sustentable', 'side', 'wood', 'floor', 'madera',
]

# Patrones para PÁGINAS LEGALES (FUNCIONAL pero mantener)
LEGAL_PATTERNS = [
    r'politica-privacidad',
    r'reembolso',
    r'terminos',
    r'condiciones',
]


# ============================================================================
# UTILIDADES
# ============================================================================
def normalize_url(url: str) -> str:
    """Normaliza una URL: minúsculas, sin trailing slash extra, sin \\r."""
    url = url.strip().rstrip('\r').rstrip('\n')
    url = url.lower()
    # Quitar trailing slash si no es la home
    if url.endswith('/') and url.count('/') > 3:
        url = url.rstrip('/')
    return url


def url_to_path(url: str) -> str:
    """Convierte URL completa a source_path: https://www.not-wood.cl/foo → /foo"""
    parsed = urlparse(url)
    path = parsed.path or '/'
    if parsed.query:
        path += '?' + parsed.query
    return path


def is_functional(url: str) -> bool:
    """Determina si una URL es funcional (no se migra manualmente)."""
    for pattern in FUNCTIONAL_PATTERNS:
        if re.search(pattern, url):
            return True
    return False


def is_legal(url: str) -> bool:
    """Determina si una URL es de páginas legales."""
    for pattern in LEGAL_PATTERNS:
        if re.search(pattern, url):
            return True
    return False


def is_category_page(url: str) -> bool:
    """Determina si una URL es página de categoría/marca (no producto individual)."""
    path = url_to_path(url).strip('/')

    # Es la homepage
    if not path:
        return True

    # Tiene subpaths (ej: /revestimientos-.../resistente-al-agua/)
    if '/' in path:
        return True

    # Contiene palabras de categoría/marca
    for kw in CATEGORY_KEYWORDS:
        if kw in path:
            return True

    return False


def is_product(url: str) -> bool:
    """Heurística: las fichas de producto suelen tener nombres descriptivos largos."""
    path = url_to_path(url).strip('/')

    # Productos típicos en Not Wood
    product_indicators = [
        r'banca-',           # bancas
        r'eco-basurero-',    # basureros
        r'^revestimiento-(muro|de|tablon|para)',  # productos específicos de revestimiento
        r'^piso-vinilico-',  # pisos
        r'^union-',          # accesorios de unión
        r'^corta-vista-',    # corta vistas
        r'^panel-',          # paneles
        r'^deck-',           # decks
    ]

    for pattern in product_indicators:
        if re.search(pattern, path):
            return True

    return False


def categorize_url(url: str, is_sitelink: bool, has_good_score: bool) -> str:
    """Determina la prioridad final de una URL."""

    # Funcional WooCommerce / taxonomías
    if is_functional(url):
        return 'FUNCTIONAL'

    # Legal
    if is_legal(url):
        return 'LEGAL'

    # En ambos archivos = HIGH-CRITICAL
    if is_sitelink and has_good_score:
        return 'HIGH-CRITICAL'

    # Solo en buena puntuación = HIGH
    if has_good_score:
        return 'HIGH'

    # Solo en sitelinks:
    if is_sitelink:
        # Si es página de categoría = MEDIUM
        if is_category_page(url) and not is_product(url):
            return 'MEDIUM'
        # Si es producto = LOW (irá vía CSV WooCommerce)
        if is_product(url):
            return 'LOW'
        # Otros = MEDIUM por defecto (mejor seguro)
        return 'MEDIUM'

    return 'LOW'


# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Priority Builder — Not Wood')
    parser.add_argument('--sitelinks', default='sitelinks.txt')
    parser.add_argument('--buenas', default='enlances-puntuacion-buena.txt')
    parser.add_argument('--output', default='url_mapping_curado.csv')
    parser.add_argument('--report', default='priority_report.txt')
    args = parser.parse_args()

    # Cargar archivos
    sitelinks = set()
    if Path(args.sitelinks).exists():
        with open(args.sitelinks, 'r', encoding='utf-8') as f:
            for line in f:
                url = normalize_url(line)
                if url:
                    sitelinks.add(url)

    buenas = set()
    if Path(args.buenas).exists():
        with open(args.buenas, 'r', encoding='utf-8') as f:
            for line in f:
                url = normalize_url(line)
                if url:
                    buenas.add(url)

    # Unión de ambos sets
    all_urls = sitelinks | buenas

    print(f"📊 Sitelinks:          {len(sitelinks)}")
    print(f"📊 Buena puntuación:   {len(buenas)}")
    print(f"📊 Total único:        {len(all_urls)}")
    print()

    # Procesar y clasificar
    classified = []
    for url in sorted(all_urls):
        is_sl = url in sitelinks
        has_good = url in buenas
        priority = categorize_url(url, is_sl, has_good)

        classified.append({
            'url_full': url,
            'source_path': url_to_path(url),
            'priority': priority,
            'is_sitelink': 'True' if is_sl else 'False',
            'has_good_score': 'True' if has_good else 'False',
            'is_product': 'True' if is_product(url) else 'False',
            'migration_strategy': get_strategy(priority),
        })

    # Estadísticas por prioridad
    from collections import Counter
    priority_counts = Counter(c['priority'] for c in classified)

    print(f"📋 DISTRIBUCIÓN POR PRIORIDAD:")
    for priority in ['HIGH-CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'LEGAL', 'FUNCTIONAL']:
        count = priority_counts.get(priority, 0)
        bar = '█' * min(count, 50)
        print(f"   {priority:15s} {count:4d}  {bar}")

    # Guardar CSV
    fieldnames = ['url_full', 'source_path', 'priority', 'is_sitelink',
                  'has_good_score', 'is_product', 'migration_strategy']
    with open(args.output, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(classified)

    print(f"\n✅ CSV generado: {args.output}")

    # Generar reporte detallado
    generate_text_report(classified, priority_counts, args.report)
    print(f"📄 Reporte detallado: {args.report}")

    # Sugerencias
    high_critical = priority_counts.get('HIGH-CRITICAL', 0)
    high = priority_counts.get('HIGH', 0)
    medium = priority_counts.get('MEDIUM', 0)
    low = priority_counts.get('LOW', 0)

    print(f"\n{'='*65}")
    print(f"💡 PLAN SUGERIDO PARA EL LUNES:")
    print(f"{'='*65}")
    print(f"   FASE 1 (CRÍTICA — para lanzamiento):")
    print(f"      HIGH-CRITICAL ({high_critical}) + HIGH ({high}) = {high_critical+high} URLs")
    print(f"      Migración manual con kits del Migrator Co")
    print(f"      Tiempo estimado: {(high_critical+high)*30/60:.1f} horas diseñador")
    print(f"")
    print(f"   FASE 2 (DESEABLE — antes del lunes si hay tiempo):")
    print(f"      MEDIUM ({medium} URLs)")
    print(f"      Tiempo estimado: {medium*25/60:.1f} horas diseñador")
    print(f"")
    print(f"   FASE 3 (POST-LANZAMIENTO):")
    print(f"      LOW ({low} URLs) → Importar vía WooCommerce CSV")
    print(f"      LEGAL ({priority_counts.get('LEGAL', 0)}) → Copiar manual (1h)")
    print(f"      FUNCTIONAL ({priority_counts.get('FUNCTIONAL', 0)}) → Auto-gestionado")
    print(f"{'='*65}")


def get_strategy(priority: str) -> str:
    """Mapea prioridad a estrategia de migración."""
    strategies = {
        'HIGH-CRITICAL': 'Migrator Co — Kit completo con screenshots',
        'HIGH': 'Migrator Co — Kit completo',
        'MEDIUM': 'Migrator Co — Kit simplificado',
        'LOW': 'WooCommerce CSV Import',
        'LEGAL': 'Copia manual del texto',
        'FUNCTIONAL': 'Auto-gestionado por WordPress/WooCommerce',
    }
    return strategies.get(priority, 'Revisar manualmente')


def generate_text_report(classified, priority_counts, output_path):
    """Genera reporte detallado en texto plano."""
    lines = []
    lines.append("=" * 80)
    lines.append("REPORTE DE PRIORIZACIÓN — NOT WOOD MIGRATION")
    lines.append("=" * 80)
    lines.append("")

    for priority in ['HIGH-CRITICAL', 'HIGH', 'MEDIUM', 'LEGAL', 'FUNCTIONAL', 'LOW']:
        urls = [c for c in classified if c['priority'] == priority]
        if not urls:
            continue

        lines.append(f"\n{'─' * 80}")
        lines.append(f"📌 {priority} — {len(urls)} URLs")
        lines.append(f"   Estrategia: {get_strategy(priority)}")
        lines.append(f"{'─' * 80}")

        for u in urls:
            indicators = []
            if u['is_sitelink'] == 'True':
                indicators.append('SITELINK')
            if u['has_good_score'] == 'True':
                indicators.append('BUEN SCORE')
            if u['is_product'] == 'True':
                indicators.append('PRODUCTO')
            ind_str = f"  [{', '.join(indicators)}]" if indicators else ''
            lines.append(f"  • {u['source_path']}{ind_str}")

    Path(output_path).write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()