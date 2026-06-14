#!/usr/bin/env python3
"""
Rank Math Score Extractor — Not Wood Edition
=============================================
Script auxiliar para extraer las puntuaciones SEO reales de cada URL
desde Rank Math (vía REST API autenticada) y RE-PRIORIZAR el CSV de mapping.

¿POR QUÉ ESTE SCRIPT?
La extracción inicial dejó rank_score = 0 para todas las URLs.
Este script consulta Rank Math directamente y genera un CSV actualizado
con las puntuaciones reales, permitiendo decidir mejor qué URLs migrar
con prioridad HIGH (manual con kit) vs LOW (productos vía CSV).

USO:
    python rank_math_score_extractor.py

OUTPUT:
    url_mapping_reference_v2.csv — CSV actualizado con scores reales
    rank_scores_report.html — Reporte visual de scores
"""

import csv
import json
import time
import sys
from pathlib import Path
from urllib.parse import urljoin
from base64 import b64encode
from datetime import datetime

import requests

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
SITE_ORIGEN = "https://www.not-wood.cl"
CSV_INPUT = "url_mapping_reference.csv"
CSV_OUTPUT = "url_mapping_reference_v2.csv"
REPORT_HTML = "rank_scores_report.html"

# Credenciales Application Password
WP_USERNAME = "TU_USUARIO_WP"
WP_APP_PASSWORD = "xxxx xxxx xxxx xxxx xxxx xxxx"

# Umbrales de priorización (ajustables)
THRESHOLD_HIGH = 80   # Score >= 80 → HIGH
THRESHOLD_MEDIUM = 60 # Score >= 60 y < 80 → MEDIUM
                      # Score < 60 → LOW

REQUEST_TIMEOUT = 30
USER_AGENT = "Migrator-Co/1.0 (Latino Digital)"


# ============================================================================
# UTILIDADES
# ============================================================================
def get_auth_header():
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    encoded = b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded}", 'User-Agent': USER_AGENT}


def categorize_priority(score: int, is_sitelink: bool = False) -> str:
    """Categoriza prioridad basado en score y sitelink."""
    if is_sitelink:
        return "HIGH"  # Sitelinks siempre son críticos
    if score >= THRESHOLD_HIGH:
        return "HIGH"
    elif score >= THRESHOLD_MEDIUM:
        return "MEDIUM"
    return "LOW"


# ============================================================================
# EXTRACCIÓN DE RANK SCORE
# ============================================================================
def get_post_id_by_slug(slug: str, auth_header: dict) -> tuple[int, str] | None:
    """Obtiene el post ID y endpoint donde vive el slug."""
    if not slug or slug == '/':
        # Homepage: buscar la página marcada como front_page en site options
        try:
            r = requests.get(
                f"{SITE_ORIGEN}/wp-json/wp/v2/pages?per_page=100",
                headers=auth_header,
                timeout=REQUEST_TIMEOUT
            )
            r.raise_for_status()
            # Buscar la primera con menu_order=0 o título tipo "Home"
            pages = r.json()
            for p in pages:
                title = p.get('title', {}).get('rendered', '').lower()
                if 'home' in title or 'inicio' in title or p.get('menu_order') == 0:
                    return p['id'], 'pages'
            return pages[0]['id'], 'pages' if pages else None
        except Exception:
            return None

    for endpoint in ['pages', 'posts', 'product']:
        try:
            r = requests.get(
                f"{SITE_ORIGEN}/wp-json/wp/v2/{endpoint}",
                params={'slug': slug},
                headers=auth_header,
                timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return data[0]['id'], endpoint
        except Exception:
            continue
    return None


def get_rank_score(post_id: int, endpoint: str, auth_header: dict) -> dict:
    """
    Obtiene el rank score y metadata SEO de Rank Math para un post.

    Rank Math guarda los scores en post_meta con estas claves:
    - rank_math_seo_score (integer 0-100)
    - rank_math_focus_keyword
    - rank_math_title
    - rank_math_description
    """
    try:
        # Pedir el post completo con _embed para obtener meta fields
        r = requests.get(
            f"{SITE_ORIGEN}/wp-json/wp/v2/{endpoint}/{post_id}",
            params={'_fields': 'id,title,slug,meta,rank_math'},
            headers=auth_header,
            timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        data = r.json()

        # El score puede estar en distintos lugares según la versión de Rank Math
        score = 0
        focus_kw = ''
        meta_title = ''
        meta_desc = ''

        meta = data.get('meta', {})
        if isinstance(meta, dict):
            score = int(meta.get('rank_math_seo_score', 0) or 0)
            focus_kw = meta.get('rank_math_focus_keyword', '')
            meta_title = meta.get('rank_math_title', '')
            meta_desc = meta.get('rank_math_description', '')

        # Fallback: intentar endpoint nativo de Rank Math
        if score == 0:
            try:
                rm_url = f"{SITE_ORIGEN}/wp-json/rankmath/v1/get-head?url={SITE_ORIGEN}{data.get('slug', '')}"
                rm_r = requests.get(rm_url, headers=auth_header, timeout=REQUEST_TIMEOUT)
                if rm_r.status_code == 200:
                    rm_data = rm_r.json()
                    # Rank Math expone score en diferentes paths según versión
                    score = int(rm_data.get('score', 0) or rm_data.get('seo_score', 0) or 0)
            except Exception:
                pass

        return {
            'score': score,
            'focus_keyword': focus_kw,
            'meta_title': meta_title,
            'meta_description': meta_desc,
            'title': data.get('title', {}).get('rendered', ''),
        }
    except Exception as e:
        return {'score': 0, 'error': str(e)}


# ============================================================================
# REPORTE HTML
# ============================================================================
def generate_html_report(rows: list, output_path: str):
    """Genera reporte HTML con distribución visual de scores."""
    rows_sorted = sorted(rows, key=lambda r: -int(r.get('rank_score', 0)))

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Rank Math Score Report — Not Wood</title>
<style>
    body {{ font-family: -apple-system, sans-serif; max-width: 1200px; margin: 2rem auto; padding: 1rem; }}
    h1 {{ color: #2e7d32; }}
    .summary {{ display: flex; gap: 1rem; margin: 1.5rem 0; }}
    .stat-card {{ flex: 1; padding: 1rem; border-radius: 8px; text-align: center; }}
    .stat-card.high {{ background: #c62828; color: white; }}
    .stat-card.medium {{ background: #f9a825; color: white; }}
    .stat-card.low {{ background: #757575; color: white; }}
    .stat-card .count {{ font-size: 2.5rem; font-weight: bold; }}
    table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
    th {{ background: #2e7d32; color: white; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 10px; font-weight: bold; font-size: 0.85rem; }}
    .badge-HIGH {{ background: #c62828; color: white; }}
    .badge-MEDIUM {{ background: #f9a825; color: white; }}
    .badge-LOW {{ background: #757575; color: white; }}
    .score-bar {{ display: inline-block; width: 100px; height: 8px; background: #eee; border-radius: 4px; vertical-align: middle; margin-right: 5px; }}
    .score-fill {{ height: 100%; border-radius: 4px; }}
    .score-fill-high {{ background: #2e7d32; }}
    .score-fill-medium {{ background: #f9a825; }}
    .score-fill-low {{ background: #c62828; }}
</style>
</head>
<body>
<h1>📊 Rank Math Score Report — Not Wood</h1>
<p>Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
"""

    high = sum(1 for r in rows_sorted if r.get('priority') == 'HIGH')
    medium = sum(1 for r in rows_sorted if r.get('priority') == 'MEDIUM')
    low = sum(1 for r in rows_sorted if r.get('priority') == 'LOW')

    html += f"""
<div class="summary">
    <div class="stat-card high">
        <div>HIGH</div>
        <div class="count">{high}</div>
        <div>Score ≥ {THRESHOLD_HIGH} o sitelink</div>
    </div>
    <div class="stat-card medium">
        <div>MEDIUM</div>
        <div class="count">{medium}</div>
        <div>Score {THRESHOLD_MEDIUM}-{THRESHOLD_HIGH-1}</div>
    </div>
    <div class="stat-card low">
        <div>LOW</div>
        <div class="count">{low}</div>
        <div>Score &lt; {THRESHOLD_MEDIUM}</div>
    </div>
</div>

<h2>Estrategia recomendada</h2>
<ul>
    <li><strong>HIGH ({high} URLs):</strong> Migración manual con Migrator Co (kits para diseñador)</li>
    <li><strong>MEDIUM ({medium} URLs):</strong> Migración semi-asistida (kits simplificados + templates)</li>
    <li><strong>LOW ({low} URLs):</strong> Importación masiva vía WooCommerce CSV</li>
</ul>

<h2>Detalle por URL (ordenado por score)</h2>
<table>
<tr>
    <th>#</th>
    <th>Source Path</th>
    <th>Title</th>
    <th>Score</th>
    <th>Focus Keyword</th>
    <th>Sitelink</th>
    <th>Prioridad</th>
</tr>
"""

    for i, row in enumerate(rows_sorted, 1):
        score = int(row.get('rank_score', 0))
        score_class = 'high' if score >= THRESHOLD_HIGH else ('medium' if score >= THRESHOLD_MEDIUM else 'low')
        priority = row.get('priority', 'LOW')

        html += f"""
<tr>
    <td>{i}</td>
    <td><code>{row.get('source_path', '')}</code></td>
    <td>{row.get('title', '—')[:60]}</td>
    <td>
        <div class="score-bar"><div class="score-fill score-fill-{score_class}" style="width:{score}%"></div></div>
        {score}
    </td>
    <td>{row.get('focus_keyword', '—')}</td>
    <td>{'⭐' if row.get('is_sitelink') == 'True' else ''}</td>
    <td><span class="badge badge-{priority}">{priority}</span></td>
</tr>
"""

    html += "</table></body></html>"
    Path(output_path).write_text(html, encoding='utf-8')


# ============================================================================
# MAIN
# ============================================================================
def main():
    print("🔍 Rank Math Score Extractor — Not Wood Edition\n")

    # Validar credenciales
    if WP_USERNAME == "TU_USUARIO_WP" or WP_APP_PASSWORD.startswith("xxxx"):
        print("❌ ERROR: Configura WP_USERNAME y WP_APP_PASSWORD en el script.")
        print("   Para generar: WP Admin > Usuarios > Perfil > Application Passwords")
        sys.exit(1)

    auth = get_auth_header()

    # Cargar CSV
    if not Path(CSV_INPUT).exists():
        print(f"❌ No se encontró: {CSV_INPUT}")
        sys.exit(1)

    rows = []
    with open(CSV_INPUT, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): (v.strip() if v else '') for k, v in row.items()}
            if row.get('source_path'):
                rows.append(row)

    # Agregar homepage si falta
    if not any(r['source_path'] == '/' for r in rows):
        print("ℹ️  Agregando homepage (/) al listado")
        rows.insert(0, {
            'source_path': '/',
            'target_path_placeholder': '/',
            'rank_score': '0',
            'is_sitelink': 'True',
            'priority': 'HIGH',
        })

    print(f"📋 Procesando {len(rows)} URLs...\n")

    # Procesar cada URL
    enriched = []
    for i, row in enumerate(rows, 1):
        source_path = row['source_path']
        slug = source_path.strip('/').split('/')[-1] if source_path != '/' else ''

        print(f"[{i}/{len(rows)}] {source_path}", end=' ... ')

        # 1. Obtener post ID
        post_info = get_post_id_by_slug(slug, auth)
        if not post_info:
            print("⚠️  no encontrado")
            row['rank_score'] = 0
            row['priority'] = row.get('priority', 'LOW')
            enriched.append(row)
            continue

        post_id, endpoint = post_info

        # 2. Obtener rank score
        score_data = get_rank_score(post_id, endpoint, auth)
        score = score_data.get('score', 0)
        focus_kw = score_data.get('focus_keyword', '')
        title = score_data.get('title', '')

        # 3. Re-priorizar
        is_sitelink = row.get('is_sitelink', 'False') == 'True'
        new_priority = categorize_priority(score, is_sitelink)

        row['rank_score'] = score
        row['focus_keyword'] = focus_kw
        row['title'] = title
        row['priority'] = new_priority
        row['post_id'] = post_id
        row['endpoint'] = endpoint

        enriched.append(row)
        print(f"score={score} → {new_priority}")

        # Rate limiting amistoso
        time.sleep(0.3)

    # Guardar CSV enriquecido
    fieldnames = ['source_path', 'target_path_placeholder', 'rank_score',
                  'is_sitelink', 'priority', 'focus_keyword', 'title',
                  'post_id', 'endpoint']

    with open(CSV_OUTPUT, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(enriched)

    # Generar reporte HTML
    generate_html_report(enriched, REPORT_HTML)

    # Estadísticas finales
    high = sum(1 for r in enriched if r.get('priority') == 'HIGH')
    medium = sum(1 for r in enriched if r.get('priority') == 'MEDIUM')
    low = sum(1 for r in enriched if r.get('priority') == 'LOW')

    print(f"\n{'='*60}")
    print(f"✅ Proceso completado")
    print(f"   HIGH:   {high} URLs")
    print(f"   MEDIUM: {medium} URLs")
    print(f"   LOW:    {low} URLs")
    print(f"\n📄 CSV actualizado: {CSV_OUTPUT}")
    print(f"📊 Reporte visual: {REPORT_HTML}")
    print(f"{'='*60}")
    print(f"\n💡 Próximo paso:")
    print(f"   python migrator_co_notwood.py --csv {CSV_OUTPUT} --priority HIGH")


if __name__ == '__main__':
    main()
    