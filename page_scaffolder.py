#!/usr/bin/env python3
"""
Page Scaffolder — Not Wood Edition
===================================
Crea masivamente las páginas vacías en dev.not-wood.cl con:
- Slug exacto del source_path (preserva 301s)
- Title configurado
- Meta title y description de Rank Math (postmeta)
- Canonical URL
- Open Graph (postmeta de Rank Math)
- Estado: DRAFT (borrador, no publicado)

Las páginas quedan listas para que el usuario las abra en Elementor
y haga la maquetación manual o aplique un template.

¿Por qué este script?
- Eliminar clicks repetitivos de WP Admin
- Garantizar ZERO typos en slugs (críticos para SEO)
- Pre-configurar metadata Rank Math sin abrir cada página
- Detectar páginas ya existentes y actualizarlas en vez de duplicar

USO BÁSICO:
    python page_scaffolder.py \\
        --csv insumos\\url_mapping_curado.csv \\
        --seo-csv insumos\\seo_metadata_complete.csv \\
        --priority HIGH-CRITICAL,HIGH

USO DRY-RUN (recomendado primera vez):
    python page_scaffolder.py \\
        --csv insumos\\url_mapping_curado.csv \\
        --seo-csv insumos\\seo_metadata_complete.csv \\
        --priority HIGH-CRITICAL,HIGH \\
        --dry-run
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from base64 import b64encode
from datetime import datetime

import requests


# ============================================================================
# CONFIGURACIÓN — EDITAR ANTES DE EJECUTAR
# ============================================================================

# Staging donde se crearán las páginas
STAGING_SITE = "https://dev.not-wood.cl"

# Credenciales Application Password del STAGING (NO de producción)
# Generadas en: dev.not-wood.cl/wp-admin > Usuarios > Perfil > Application Passwords
STAGING_USERNAME = "Camilo"
STAGING_APP_PASSWORD = "iESP TQLl 58ku a4jg S5AQ r0MC"

# Status inicial de las páginas creadas
# Opciones: 'draft' (recomendado), 'publish', 'private'
DEFAULT_STATUS = 'draft'

# Configuración técnica
REQUEST_TIMEOUT = 30
USER_AGENT = "Migrator-Co-Page-Scaffolder/1.0"
DELAY_BETWEEN_REQUESTS = 0.3


# ============================================================================
# AUTENTICACIÓN
# ============================================================================
def get_auth_header():
    """HTTP Basic Auth para REST API del staging."""
    if STAGING_USERNAME == "TU_USUARIO_STAGING" or STAGING_APP_PASSWORD.startswith("xxxx"):
        return None
    credentials = f"{STAGING_USERNAME}:{STAGING_APP_PASSWORD}"
    encoded = b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }


# ============================================================================
# CARGA DE DATOS
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


def load_seo_metadata(csv_path: str) -> dict:
    """Carga el CSV de seo_metadata_complete y lo indexa por source_path."""
    indexed = {}
    if not Path(csv_path).exists():
        print(f"⚠️  No se encontró {csv_path}. Se crearán páginas SIN metadata SEO.")
        return indexed

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): (v.strip() if v else '') for k, v in row.items()}
            source_path = row.get('source_path', '')
            if source_path:
                indexed[source_path] = row
    return indexed


# ============================================================================
# OPERACIONES REST API
# ============================================================================
def check_existing_page(slug: str, headers: dict) -> dict:
    """Busca si ya existe una página con ese slug."""
    if slug == '' or slug == '/':
        slug = ''  # Homepage

    try:
        params = {'slug': slug} if slug else {}
        r = requests.get(
            f"{STAGING_SITE}/wp-json/wp/v2/pages",
            params=params,
            headers={k: v for k, v in headers.items() if k != 'Content-Type'},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            if data:
                return {'exists': True, 'id': data[0]['id'], 'data': data[0]}
        return {'exists': False}
    except Exception as e:
        return {'exists': False, 'error': str(e)}


def slug_from_source_path(source_path: str) -> str:
    """Extrae el slug del source_path para WordPress."""
    if source_path == '/' or source_path == '':
        return ''  # Homepage
    return source_path.strip('/').split('/')[-1]


def build_page_payload(row: dict, seo_data: dict, status: str = 'draft') -> dict:
    """Construye el payload para crear/actualizar la página."""
    source_path = row.get('source_path', '')
    slug = slug_from_source_path(source_path)
    title = seo_data.get('meta_title', '') or row.get('source_path', '')

    # Si no tenemos meta_title, usar el slug como title placeholder
    if not title or title == source_path:
        # Convertir slug a título legible
        title = slug.replace('-', ' ').title() if slug else 'Página principal'

    # Limpiar el title del separador típico de Rank Math (" — Not Wood", " | Not Wood")
    if seo_data.get('meta_title'):
        clean_title = seo_data['meta_title']
        # Quitar " | Not Wood" o " - Not Wood" del final
        for sep in [' | Not Wood', ' - Not Wood', ' — Not Wood', ' | NotWood', ' - NotWood']:
            if clean_title.endswith(sep):
                clean_title = clean_title[:-len(sep)].strip()
                break
        title = clean_title

    payload = {
        'title': title,
        'slug': slug,
        'status': status,
        'content': '<!-- Página creada por Migrator Co. Pendiente de maquetación. -->',
    }

    # Meta tags para Rank Math (vía postmeta)
    meta = {}
    if seo_data.get('meta_title'):
        meta['rank_math_title'] = seo_data['meta_title']
    if seo_data.get('meta_description'):
        meta['rank_math_description'] = seo_data['meta_description']
    if seo_data.get('canonical_url'):
        meta['rank_math_canonical_url'] = seo_data['canonical_url']
    if seo_data.get('og_title'):
        meta['rank_math_facebook_title'] = seo_data['og_title']
    if seo_data.get('og_description'):
        meta['rank_math_facebook_description'] = seo_data['og_description']
    if seo_data.get('og_image'):
        meta['rank_math_facebook_image'] = seo_data['og_image']
    if seo_data.get('twitter_title'):
        meta['rank_math_twitter_title'] = seo_data['twitter_title']
    if seo_data.get('twitter_image'):
        meta['rank_math_twitter_image'] = seo_data['twitter_image']
    if seo_data.get('robots'):
        meta['rank_math_robots'] = seo_data['robots']

    if meta:
        payload['meta'] = meta

    return payload


def create_page(payload: dict, headers: dict) -> dict:
    """Crea una nueva página vía REST API."""
    try:
        r = requests.post(
            f"{STAGING_SITE}/wp-json/wp/v2/pages",
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code in (200, 201):
            return {'success': True, 'data': r.json()}
        else:
            return {
                'success': False,
                'error': f'HTTP {r.status_code}',
                'detail': r.text[:500],
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_page(page_id: int, payload: dict, headers: dict) -> dict:
    """Actualiza una página existente vía REST API."""
    try:
        r = requests.post(
            f"{STAGING_SITE}/wp-json/wp/v2/pages/{page_id}",
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return {'success': True, 'data': r.json()}
        else:
            return {
                'success': False,
                'error': f'HTTP {r.status_code}',
                'detail': r.text[:500],
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ============================================================================
# REPORTE
# ============================================================================
def print_summary(results: list):
    """Imprime resumen en consola."""
    total = len(results)
    created = sum(1 for r in results if r.get('action') == 'CREATED')
    updated = sum(1 for r in results if r.get('action') == 'UPDATED')
    skipped = sum(1 for r in results if r.get('action') == 'SKIPPED')
    errors = sum(1 for r in results if r.get('action') == 'ERROR')

    print(f"\n{'='*65}")
    print(f"📊 RESUMEN DE EJECUCIÓN")
    print(f"{'='*65}")
    print(f"   Total URLs procesadas:    {total}")
    print(f"   🆕 CREADAS:                {created}")
    print(f"   🔄 ACTUALIZADAS:           {updated}")
    print(f"   ⏭️  OMITIDAS:               {skipped}")
    print(f"   ❌ ERROR:                  {errors}")
    print(f"{'='*65}\n")


def save_results_csv(results: list, output_path: Path):
    """Guarda resultados en CSV para tracking."""
    fieldnames = [
        'source_path', 'slug', 'title', 'priority',
        'action', 'page_id', 'wp_edit_url', 'elementor_edit_url',
        'status', 'error_detail',
    ]
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)


# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Page Scaffolder — Not Wood')
    parser.add_argument('--csv', required=True,
                        help='CSV de mapping curado (url_mapping_curado.csv)')
    parser.add_argument('--seo-csv', default='insumos/seo_metadata_complete.csv',
                        help='CSV con metadata SEO extraída')
    parser.add_argument('--priority', default='HIGH-CRITICAL,HIGH',
                        help='Prioridades a procesar (default: HIGH-CRITICAL,HIGH)')
    parser.add_argument('--status', default=DEFAULT_STATUS,
                        choices=['draft', 'publish', 'private'],
                        help=f'Status inicial de las páginas (default: {DEFAULT_STATUS})')
    parser.add_argument('--output-csv', default='insumos/scaffolder_results.csv',
                        help='CSV con resultados de la ejecución')
    parser.add_argument('--dry-run', action='store_true',
                        help='Modo simulación: no crea/modifica páginas')
    parser.add_argument('--update-existing', action='store_true',
                        help='Si una página ya existe, actualizar su metadata')
    args = parser.parse_args()

    # Validar autenticación
    headers = get_auth_header()
    if not headers:
        print("❌ Configura STAGING_USERNAME y STAGING_APP_PASSWORD en el script.")
        print("   Las credenciales son del STAGING (dev.not-wood.cl), NO de producción.")
        sys.exit(1)

    # Validar CSVs
    if not Path(args.csv).exists():
        print(f"❌ No se encontró: {args.csv}")
        sys.exit(1)

    # Parsear prioridades
    priorities = [p.strip().upper() for p in args.priority.split(',')]

    # Cargar datos
    print(f"📥 Cargando datos...")
    rows = load_mapping(args.csv, priorities)
    seo_data_by_path = load_seo_metadata(args.seo_csv)
    print(f"   ✓ {len(rows)} URLs del mapping (prioridades: {priorities})")
    print(f"   ✓ {len(seo_data_by_path)} URLs con metadata SEO")

    if not rows:
        print(f"❌ No se encontraron URLs con prioridad {priorities}")
        sys.exit(1)

    print(f"\n📋 Configuración:")
    print(f"   Staging:           {STAGING_SITE}")
    print(f"   Usuario:           {STAGING_USERNAME}")
    print(f"   Status páginas:    {args.status}")
    print(f"   Actualizar existentes: {'SÍ' if args.update_existing else 'NO (saltar)'}")
    print(f"   Modo:              {'🧪 DRY-RUN' if args.dry_run else '🚀 EJECUCIÓN REAL'}")
    print()

    if not args.dry_run:
        confirm = input("¿Continuar con la ejecución REAL? (s/N): ")
        if confirm.strip().lower() != 's':
            print("⏹️  Cancelado por el usuario.")
            sys.exit(0)

    # Procesar
    results = []
    for i, row in enumerate(rows, 1):
        source_path = row.get('source_path', '')
        priority = row.get('priority', 'UNKNOWN')
        slug = slug_from_source_path(source_path)

        print(f"\n[{i}/{len(rows)}] [{priority}] {source_path}")

        # Datos SEO si existen
        seo_data = seo_data_by_path.get(source_path, {})
        if seo_data:
            print(f"   ℹ️  SEO encontrado: {seo_data.get('meta_title', '')[:60]}...")
        else:
            print(f"   ⚠️  Sin metadata SEO disponible")

        # Verificar si existe
        existing = check_existing_page(slug, headers)

        if existing.get('exists'):
            existing_id = existing['id']
            print(f"   ℹ️  Página ya existe (ID: {existing_id})")

            if args.update_existing:
                if args.dry_run:
                    print(f"   🧪 [DRY-RUN] Actualizaría página {existing_id}")
                    results.append({
                        'source_path': source_path,
                        'slug': slug,
                        'priority': priority,
                        'action': 'WOULD_UPDATE',
                        'page_id': existing_id,
                    })
                else:
                    payload = build_page_payload(row, seo_data, args.status)
                    # Al actualizar, NO sobrescribir content (puede tener Elementor data)
                    payload.pop('content', None)
                    result = update_page(existing_id, payload, headers)
                    if result['success']:
                        page_data = result['data']
                        print(f"   🔄 Actualizada: ID {existing_id}")
                        results.append({
                            'source_path': source_path,
                            'slug': slug,
                            'title': page_data.get('title', {}).get('rendered', ''),
                            'priority': priority,
                            'action': 'UPDATED',
                            'page_id': existing_id,
                            'wp_edit_url': f"{STAGING_SITE}/wp-admin/post.php?post={existing_id}&action=edit",
                            'elementor_edit_url': f"{STAGING_SITE}/wp-admin/post.php?post={existing_id}&action=elementor",
                            'status': args.status,
                        })
                    else:
                        print(f"   ❌ Error actualizando: {result.get('error')}")
                        results.append({
                            'source_path': source_path,
                            'slug': slug,
                            'priority': priority,
                            'action': 'ERROR',
                            'error_detail': result.get('detail', '')[:200],
                        })
            else:
                print(f"   ⏭️  Saltando (existe y --update-existing está desactivado)")
                results.append({
                    'source_path': source_path,
                    'slug': slug,
                    'priority': priority,
                    'action': 'SKIPPED',
                    'page_id': existing_id,
                    'wp_edit_url': f"{STAGING_SITE}/wp-admin/post.php?post={existing_id}&action=edit",
                })
        else:
            # Crear nueva
            payload = build_page_payload(row, seo_data, args.status)

            if args.dry_run:
                print(f"   🧪 [DRY-RUN] Crearía: title='{payload['title']}', slug='{payload['slug']}'")
                results.append({
                    'source_path': source_path,
                    'slug': slug,
                    'title': payload['title'],
                    'priority': priority,
                    'action': 'WOULD_CREATE',
                })
            else:
                result = create_page(payload, headers)
                if result['success']:
                    page_data = result['data']
                    new_id = page_data['id']
                    actual_slug = page_data.get('slug', '')
                    print(f"   🆕 Creada: ID {new_id}, slug='{actual_slug}'")

                    if actual_slug != slug:
                        print(f"   ⚠️  WordPress ajustó el slug: '{slug}' → '{actual_slug}'")

                    results.append({
                        'source_path': source_path,
                        'slug': actual_slug,
                        'title': page_data.get('title', {}).get('rendered', ''),
                        'priority': priority,
                        'action': 'CREATED',
                        'page_id': new_id,
                        'wp_edit_url': f"{STAGING_SITE}/wp-admin/post.php?post={new_id}&action=edit",
                        'elementor_edit_url': f"{STAGING_SITE}/wp-admin/post.php?post={new_id}&action=elementor",
                        'status': args.status,
                    })
                else:
                    print(f"   ❌ Error: {result.get('error')}")
                    print(f"      Detail: {result.get('detail', '')[:200]}")
                    results.append({
                        'source_path': source_path,
                        'slug': slug,
                        'priority': priority,
                        'action': 'ERROR',
                        'error_detail': result.get('detail', '')[:200],
                    })

        # Rate limiting
        time.sleep(DELAY_BETWEEN_REQUESTS)

    # Resumen
    print_summary(results)

    # Guardar CSV de resultados
    if not args.dry_run:
        output_path = Path(args.output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_results_csv(results, output_path)
        print(f"📄 Resultados guardados en: {output_path}")
        print()
        print(f"💡 Próximo paso:")
        print(f"   1. Abrir el CSV {output_path}")
        print(f"   2. Para cada página, abrir su 'elementor_edit_url'")
        print(f"   3. Maquetar contenido (o aplicar template)")
        print()


if __name__ == '__main__':
    main()
