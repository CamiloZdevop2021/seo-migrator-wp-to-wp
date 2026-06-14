#!/usr/bin/env python3
"""
Rank Math Meta Fixer — Not Wood Edition
========================================
Inyecta meta tags SEO (Rank Math) en páginas YA CREADAS del staging.

¿Por qué este script?
El page_scaffolder.py creó las 19 páginas con slugs correctos PERO
WordPress REST API filtró silenciosamente los meta tags porque
Rank Math no los registra con show_in_rest=true por defecto.

Este script complementa al scaffolder:
- page_scaffolder.py crea las páginas (estructura + slug)
- rank_math_meta_fixer.py inyecta la metadata SEO (Rank Math)

ESTRATEGIA TÉCNICA (3 intentos en orden):

INTENTO 1 — REST API estándar con context=edit
   Funciona si Rank Math expone sus meta vía REST (caso ideal)

INTENTO 2 — Endpoint específico de Rank Math
   POST /wp-json/rankmath/v1/updateMeta
   Funciona en Rank Math Pro con permisos adecuados

INTENTO 3 — Mini-plugin custom (si los anteriores fallan)
   Necesitarías instalar un mini-plugin PHP que expone
   un endpoint custom para escribir meta directamente

USO:
    # Ejecutar dry-run primero (recomendado)
    python rank_math_meta_fixer.py \\
        --csv insumos\\scaffolder_results.csv \\
        --seo-csv insumos\\seo_metadata_complete.csv \\
        --dry-run

    # Ejecución real
    python rank_math_meta_fixer.py \\
        --csv insumos\\scaffolder_results.csv \\
        --seo-csv insumos\\seo_metadata_complete.csv
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from base64 import b64encode
from datetime import datetime

import requests


# ============================================================================
# CONFIGURACIÓN — EDITAR ANTES DE EJECUTAR
# ============================================================================

# Staging donde están las páginas
STAGING_SITE = "https://dev.not-wood.cl"

# Credenciales Application Password del STAGING
STAGING_USERNAME = "Camilo"
STAGING_APP_PASSWORD = "iESP TQLl 58ku a4jg S5AQ r0MC"

# Técnico
REQUEST_TIMEOUT = 30
USER_AGENT = "Migrator-Co-MetaFixer/1.0"
DELAY_BETWEEN_REQUESTS = 0.3


# ============================================================================
# META KEYS DE RANK MATH
# ============================================================================
# Mapeo: campo del CSV → meta_key de Rank Math en wp_postmeta
RANK_MATH_META_MAPPING = {
    'meta_title':       'rank_math_title',
    'meta_description': 'rank_math_description',
    'canonical_url':    'rank_math_canonical_url',
    'robots':           'rank_math_robots',
    'og_title':         'rank_math_facebook_title',
    'og_description':   'rank_math_facebook_description',
    'og_image':         'rank_math_facebook_image',
    'twitter_title':    'rank_math_twitter_title',
    'twitter_image':    'rank_math_twitter_image',
}


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
def load_scaffolder_results(csv_path: str) -> list:
    """Carga el CSV de resultados del scaffolder."""
    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): (v.strip() if v else '') for k, v in row.items()}
            # Filtrar solo las que tienen page_id (las creadas/actualizadas)
            if row.get('page_id') and row.get('action') in ('CREATED', 'UPDATED', 'SKIPPED'):
                rows.append(row)
    return rows


def load_seo_metadata(csv_path: str) -> dict:
    """Carga el CSV de seo_metadata_complete y lo indexa por source_path."""
    indexed = {}
    if not Path(csv_path).exists():
        print(f"❌ No se encontró {csv_path}")
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
# ESTRATEGIAS DE INYECCIÓN
# ============================================================================
def try_inject_via_rankmath_endpoint(page_id: int, meta_dict: dict, headers: dict) -> dict:
    """
    INTENTO 1 — Endpoint específico de Rank Math.
    POST /wp-json/rankmath/v1/updateMeta
    """
    url = f"{STAGING_SITE}/wp-json/rankmath/v1/updateMeta"
    
    payload = {
        "objectID": page_id,
        "objectType": "post",
        "meta": meta_dict,
    }
    
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code in (200, 201):
            return {'success': True, 'method': 'rankmath_api', 'data': r.json() if r.text else {}}
        return {
            'success': False,
            'method': 'rankmath_api',
            'status_code': r.status_code,
            'error': r.text[:300] if r.text else 'Empty response',
        }
    except Exception as e:
        return {'success': False, 'method': 'rankmath_api', 'error': str(e)}


def try_inject_via_wp_rest(page_id: int, meta_dict: dict, headers: dict) -> dict:
    """
    INTENTO 2 — WP REST API estándar con meta directo.
    POST /wp-json/wp/v2/pages/{id}
    """
    url = f"{STAGING_SITE}/wp-json/wp/v2/pages/{page_id}"
    
    payload = {"meta": meta_dict}
    
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            response_data = r.json()
            # Verificar que el meta realmente se grabó
            returned_meta = response_data.get('meta', {})
            if returned_meta and any(returned_meta.get(k) for k in meta_dict.keys()):
                return {'success': True, 'method': 'wp_rest', 'data': returned_meta}
            else:
                return {
                    'success': False,
                    'method': 'wp_rest',
                    'error': 'Meta no se persistió (WordPress lo aceptó pero no lo guardó)',
                }
        return {
            'success': False,
            'method': 'wp_rest',
            'status_code': r.status_code,
            'error': r.text[:300] if r.text else 'Empty response',
        }
    except Exception as e:
        return {'success': False, 'method': 'wp_rest', 'error': str(e)}


def try_inject_via_custom_plugin(page_id: int, meta_dict: dict, headers: dict) -> dict:
    """
    INTENTO 3 — Endpoint custom del mini-plugin.
    Solo funciona si el plugin Migrator Co Meta Helper está activo en staging.
    POST /wp-json/migrator/v1/update-meta
    """
    url = f"{STAGING_SITE}/wp-json/migrator/v1/update-meta"
    
    payload = {
        "post_id": page_id,
        "meta": meta_dict,
    }
    
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code in (200, 201):
            return {'success': True, 'method': 'custom_plugin', 'data': r.json() if r.text else {}}
        return {
            'success': False,
            'method': 'custom_plugin',
            'status_code': r.status_code,
            'error': r.text[:300] if r.text else 'Plugin no instalado o endpoint no disponible',
        }
    except Exception as e:
        return {'success': False, 'method': 'custom_plugin', 'error': str(e)}


def inject_meta_with_fallback(page_id: int, meta_dict: dict, headers: dict, preferred_method: str = None) -> dict:
    """
    Intenta inyectar meta probando 3 estrategias en orden.
    Devuelve el primer método que funciona.
    """
    if preferred_method == 'custom_plugin':
        result = try_inject_via_custom_plugin(page_id, meta_dict, headers)
        if result['success']:
            return result
    
    # Intento 1: WP REST estándar
    result = try_inject_via_wp_rest(page_id, meta_dict, headers)
    if result['success']:
        return result
    
    # Intento 2: Endpoint específico de Rank Math
    result_rm = try_inject_via_rankmath_endpoint(page_id, meta_dict, headers)
    if result_rm['success']:
        return result_rm
    
    # Intento 3: Custom plugin
    result_cp = try_inject_via_custom_plugin(page_id, meta_dict, headers)
    if result_cp['success']:
        return result_cp
    
    # Todos fallaron — devolver info del último intento
    return {
        'success': False,
        'attempts': {
            'wp_rest': result.get('error', 'unknown'),
            'rankmath_api': result_rm.get('error', 'unknown'),
            'custom_plugin': result_cp.get('error', 'unknown'),
        }
    }


# ============================================================================
# VERIFICACIÓN POST-INYECCIÓN
# ============================================================================
def verify_meta_persisted(page_id: int, expected_title: str, headers: dict) -> bool:
    """Lee la página y verifica que el meta title se persistió correctamente."""
    try:
        # Quitar Content-Type para GET
        get_headers = {k: v for k, v in headers.items() if k != 'Content-Type'}
        r = requests.get(
            f"{STAGING_SITE}/wp-json/wp/v2/pages/{page_id}?context=edit",
            headers=get_headers,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return False
        
        data = r.json()
        meta = data.get('meta', {})
        if isinstance(meta, dict):
            actual_title = meta.get('rank_math_title', '')
            return actual_title == expected_title
        return False
    except Exception:
        return False


# ============================================================================
# REPORTE
# ============================================================================
def print_summary(results: list):
    """Imprime resumen en consola."""
    total = len(results)
    success = sum(1 for r in results if r.get('status') == 'OK')
    error = sum(1 for r in results if r.get('status') == 'ERROR')
    skipped = sum(1 for r in results if r.get('status') == 'SKIPPED')

    # Métodos usados
    methods = {}
    for r in results:
        m = r.get('method', '—')
        methods[m] = methods.get(m, 0) + 1

    print(f"\n{'='*65}")
    print(f"📊 RESUMEN DE INYECCIÓN DE META TAGS")
    print(f"{'='*65}")
    print(f"   Total páginas procesadas: {total}")
    print(f"   ✅ ÉXITO:                  {success}")
    print(f"   ❌ ERROR:                  {error}")
    print(f"   ⏭️  OMITIDAS:              {skipped}")
    print(f"")
    print(f"   📡 Métodos usados:")
    for method, count in methods.items():
        print(f"      {method}: {count}")
    print(f"{'='*65}\n")


def save_results_csv(results: list, output_path: Path):
    """Guarda resultados en CSV para tracking."""
    fieldnames = [
        'source_path', 'page_id', 'slug', 'meta_title',
        'status', 'method', 'verified', 'error_detail',
    ]
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)


# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Rank Math Meta Fixer — Not Wood')
    parser.add_argument('--csv', required=True,
                        help='CSV de scaffolder_results (output de page_scaffolder.py)')
    parser.add_argument('--seo-csv', required=True,
                        help='CSV de seo_metadata_complete (output de seo_meta_extractor.py)')
    parser.add_argument('--method', choices=['auto', 'wp_rest', 'rankmath_api', 'custom_plugin'],
                        default='auto',
                        help='Método específico (default: auto = probar todos)')
    parser.add_argument('--output-csv', default='insumos/meta_fixer_results.csv',
                        help='CSV con resultados de la ejecución')
    parser.add_argument('--dry-run', action='store_true',
                        help='Modo simulación: no inyecta nada')
    parser.add_argument('--verify', action='store_true',
                        help='Verificar después de inyectar (más lento pero seguro)')
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
    if not Path(args.seo_csv).exists():
        print(f"❌ No se encontró: {args.seo_csv}")
        sys.exit(1)

    # Cargar datos
    print(f"📥 Cargando datos...")
    pages = load_scaffolder_results(args.csv)
    seo_data = load_seo_metadata(args.seo_csv)
    print(f"   ✓ {len(pages)} páginas del scaffolder")
    print(f"   ✓ {len(seo_data)} URLs con metadata SEO")

    if not pages:
        print(f"❌ No hay páginas para procesar en {args.csv}")
        sys.exit(1)

    print(f"\n📋 Configuración:")
    print(f"   Staging:       {STAGING_SITE}")
    print(f"   Usuario:       {STAGING_USERNAME}")
    print(f"   Método:        {args.method}")
    print(f"   Verificar:     {'SÍ' if args.verify else 'NO'}")
    print(f"   Modo:          {'🧪 DRY-RUN' if args.dry_run else '🚀 EJECUCIÓN REAL'}")
    print()

    if not args.dry_run:
        confirm = input("¿Continuar con la ejecución REAL? (s/N): ")
        if confirm.strip().lower() != 's':
            print("⏹️  Cancelado por el usuario.")
            sys.exit(0)

    # Procesar
    results = []
    for i, page in enumerate(pages, 1):
        source_path = page.get('source_path', '')
        page_id = page.get('page_id', '')
        slug = page.get('slug', '')

        print(f"\n[{i}/{len(pages)}] {source_path} (ID: {page_id})")

        if not page_id:
            print(f"   ⚠️  Sin page_id, saltando")
            results.append({
                'source_path': source_path,
                'page_id': page_id,
                'slug': slug,
                'status': 'SKIPPED',
                'error_detail': 'page_id vacío',
            })
            continue

        # Buscar metadata SEO
        seo = seo_data.get(source_path, {})
        if not seo:
            print(f"   ⚠️  Sin metadata SEO, saltando")
            results.append({
                'source_path': source_path,
                'page_id': page_id,
                'slug': slug,
                'status': 'SKIPPED',
                'error_detail': 'Sin metadata SEO disponible',
            })
            continue

        # Construir meta_dict para Rank Math
        meta_dict = {}
        for csv_field, rm_meta_key in RANK_MATH_META_MAPPING.items():
            value = seo.get(csv_field, '').strip()
            if value:
                meta_dict[rm_meta_key] = value

        if not meta_dict:
            print(f"   ⚠️  No hay campos SEO para inyectar")
            results.append({
                'source_path': source_path,
                'page_id': page_id,
                'slug': slug,
                'status': 'SKIPPED',
                'error_detail': 'Todos los campos SEO vacíos',
            })
            continue

        meta_title = meta_dict.get('rank_math_title', '')[:60]
        print(f"   ℹ️  Meta a inyectar:")
        print(f"      title: {meta_title}...")
        print(f"      campos: {len(meta_dict)} ({', '.join(meta_dict.keys())})")

        if args.dry_run:
            print(f"   🧪 [DRY-RUN] Inyectaría {len(meta_dict)} meta keys")
            results.append({
                'source_path': source_path,
                'page_id': page_id,
                'slug': slug,
                'meta_title': meta_dict.get('rank_math_title', ''),
                'status': 'DRY_RUN_OK',
                'method': 'simulated',
            })
        else:
            # Inyectar
            if args.method == 'auto':
                result = inject_meta_with_fallback(int(page_id), meta_dict, headers)
            elif args.method == 'wp_rest':
                result = try_inject_via_wp_rest(int(page_id), meta_dict, headers)
            elif args.method == 'rankmath_api':
                result = try_inject_via_rankmath_endpoint(int(page_id), meta_dict, headers)
            elif args.method == 'custom_plugin':
                result = try_inject_via_custom_plugin(int(page_id), meta_dict, headers)

            if result.get('success'):
                method_used = result.get('method', 'unknown')
                print(f"   ✅ Inyectado vía: {method_used}")

                # Verificación opcional
                verified = False
                if args.verify:
                    expected_title = meta_dict.get('rank_math_title', '')
                    verified = verify_meta_persisted(int(page_id), expected_title, headers)
                    if verified:
                        print(f"   ✅ Verificado: meta_title persistido correctamente")
                    else:
                        print(f"   ⚠️  Verificación falló: el meta no se persistió")

                results.append({
                    'source_path': source_path,
                    'page_id': page_id,
                    'slug': slug,
                    'meta_title': meta_dict.get('rank_math_title', ''),
                    'status': 'OK',
                    'method': method_used,
                    'verified': 'YES' if verified else ('SKIPPED' if not args.verify else 'NO'),
                })
            else:
                attempts = result.get('attempts', {})
                error_summary = '; '.join([f"{m}: {e[:80]}" for m, e in attempts.items()]) if attempts else result.get('error', 'unknown')
                print(f"   ❌ FALLÓ todos los métodos")
                print(f"      Detalle: {error_summary[:200]}")
                results.append({
                    'source_path': source_path,
                    'page_id': page_id,
                    'slug': slug,
                    'meta_title': meta_dict.get('rank_math_title', ''),
                    'status': 'ERROR',
                    'method': 'all_failed',
                    'error_detail': error_summary[:500],
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

        # Si hubo errores generalizados, sugerir el plugin
        error_count = sum(1 for r in results if r.get('status') == 'ERROR')
        if error_count > len(results) * 0.5:
            print(f"⚠️  La mayoría de los intentos fallaron.")
            print(f"   Esto indica que la REST API del staging no permite escribir")
            print(f"   los meta_keys de Rank Math directamente.")
            print(f"")
            print(f"💡 SOLUCIÓN: Instalar el mini-plugin Migrator Co Meta Helper")
            print(f"   1. Crear archivo: migrator-meta-helper.php (ver plugin entregado)")
            print(f"   2. Subir a: dev.not-wood.cl/wp-content/plugins/")
            print(f"   3. Activar en WP Admin → Plugins")
            print(f"   4. Re-ejecutar este script")
            print()


if __name__ == '__main__':
    main()
