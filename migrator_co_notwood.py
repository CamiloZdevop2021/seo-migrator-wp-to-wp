#!/usr/bin/env python3
"""
Migrator Co — Not Wood Edition
================================
Script de extracción de Kit de Migración WPBakery → Elementor
adaptado al proyecto Not Wood (not-wood.cl → dev.not-wood.cl).

CARACTERÍSTICAS:
- Lee URLs directamente del url_mapping_reference.csv
- Autenticación REST API por Application Password
- Fallback automático a scraping HTML si REST API falla
- Procesa HIGH primero, LOW después
- Reportes separados por prioridad

USO:
    # Procesar solo URLs HIGH (críticas para lanzamiento)
    python migrator_co_notwood.py --priority HIGH

    # Procesar todo (HIGH + LOW)
    python migrator_co_notwood.py --priority ALL

    # Modo dry-run (solo lista qué procesaría, sin descargar)
    python migrator_co_notwood.py --priority HIGH --dry-run
"""

import argparse
import json
import re
import os
import csv
import sys
from pathlib import Path
from urllib.parse import urlparse, urljoin
from datetime import datetime
from base64 import b64encode

import requests
from bs4 import BeautifulSoup
from slugify import slugify

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️  Playwright no instalado. Screenshots desactivados.")


# ============================================================================
# CONFIGURACIÓN — AJUSTAR ANTES DE EJECUTAR
# ============================================================================

# Dominio de producción (origen)
SITE_ORIGEN = "https://www.not-wood.cl"

# Path al CSV de mapeo
CSV_MAPPING_PATH = "url_mapping_reference.csv"

# Carpeta de salida
OUTPUT_BASE = "./migracion-staging"

# Credenciales REST API (Application Password)
# Generarlas en: WP Admin > Usuarios > Perfil > Application Passwords
WP_USERNAME = "Camilo"
WP_APP_PASSWORD = "ruYs VSnl zIzX QyaY V1lb 4wts"  # 24 chars con espacios

# Configuración técnica
REQUEST_TIMEOUT = 30
USER_AGENT = "Migrator-Co/1.0 (Latino Digital)"


# ============================================================================
# UTILIDADES
# ============================================================================
def get_auth_header():
    """Construye header de autenticación HTTP Basic para REST API."""
    if WP_USERNAME == "TU_USUARIO_WP" or WP_APP_PASSWORD.startswith("xxxx"):
        return None
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    encoded = b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def build_full_url(source_path: str) -> str:
    """Convierte /accesorios → https://www.not-wood.cl/accesorios"""
    return urljoin(SITE_ORIGEN, source_path)


def is_internal_link(url: str, base_domain: str) -> bool:
    """Determina si un enlace es interno al sitio."""
    parsed = urlparse(url)
    if not parsed.netloc:
        return True
    return parsed.netloc.replace('www.', '') == base_domain.replace('www.', '')


def slug_to_dirname(source_path: str) -> str:
    """Convierte /perfil-y-accesorios/ → perfil-y-accesorios"""
    clean = source_path.strip('/').replace('/', '__')
    return slugify(clean) if clean else 'home'


# ============================================================================
# EXTRACCIÓN: REST API (con autenticación)
# ============================================================================
def fetch_via_rest_api(source_path: str) -> dict | None:
    """Intenta obtener contenido vía REST API autenticada."""
    auth = get_auth_header()
    if not auth:
        return None

    slug = source_path.strip('/').split('/')[-1] or None
    api_base = f"{SITE_ORIGEN}/wp-json/wp/v2"

    # Si es homepage, buscar página marcada como front_page
    if not slug:
        try:
            r = requests.get(
                f"{api_base}/pages",
                params={'per_page': 100},
                headers={**auth, 'User-Agent': USER_AGENT},
                timeout=REQUEST_TIMEOUT
            )
            r.raise_for_status()
            # WordPress no marca explícitamente front_page en REST, intentamos por orden
            pages = r.json()
            if pages:
                return {**pages[0], '_endpoint': 'pages_homepage'}
        except Exception as e:
            print(f"     ⚠️  Error consultando homepage: {e}")
            return None

    # Probar en distintos endpoints (pages, posts, product)
    for endpoint in ['pages', 'posts', 'product']:
        try:
            r = requests.get(
                f"{api_base}/{endpoint}",
                params={'slug': slug, '_embed': 1},
                headers={**auth, 'User-Agent': USER_AGENT},
                timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return {**data[0], '_endpoint': endpoint}
        except Exception:
            continue

    return None


# ============================================================================
# EXTRACCIÓN: Scraping HTML (fallback)
# ============================================================================
def fetch_via_html_scraping(url: str) -> dict | None:
    """Fallback: obtiene el HTML público y construye estructura mínima."""
    try:
        r = requests.get(
            url,
            headers={'User-Agent': USER_AGENT},
            timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()

        soup = BeautifulSoup(r.text, 'html.parser')

        # Construir objeto similar al REST API
        title = soup.find('title')
        meta_desc = soup.find('meta', attrs={'name': 'description'})

        return {
            '_endpoint': 'html_scraping',
            'title': {'rendered': title.get_text() if title else ''},
            'content': {'rendered': str(soup.find('main') or soup.find('article') or soup.body)},
            'slug': urlparse(url).path.strip('/').split('/')[-1] or 'home',
            'meta_description': meta_desc.get('content', '') if meta_desc else '',
            '_raw_html': r.text,
        }
    except Exception as e:
        print(f"     ⚠️  Error en scraping HTML: {e}")
        return None


# ============================================================================
# PARSING DE CONTENIDO
# ============================================================================
def clean_shortcodes(content: str) -> str:
    """Elimina shortcodes WPBakery dejando solo el texto/HTML útil."""
    content = re.sub(r'\[/?vc_[^\]]*\]', '', content)
    content = re.sub(r'\[/?(?:row|column|column_text|btn|single_image)[^\]]*\]', '', content)
    return content.strip()


def extract_wpbakery_structure(content: str) -> list:
    """Detecta la estructura de columnas/secciones del contenido WPBakery."""
    structure = []
    rows = re.findall(r'\[vc_row[^\]]*\](.*?)\[/vc_row\]', content, re.DOTALL)
    for i, row in enumerate(rows, 1):
        columns = re.findall(r'\[vc_column\s*([^\]]*)\]', row)
        widths = []
        for col_attrs in columns:
            width_match = re.search(r'width="([^"]+)"', col_attrs)
            widths.append(width_match.group(1) if width_match else '1/1')
        structure.append({
            'row_index': i,
            'columns': len(columns),
            'widths': widths
        })
    return structure


def parse_rendered_content(html: str, base_domain: str) -> dict:
    """Parsea HTML renderizado y extrae estructura semántica."""
    soup = BeautifulSoup(html, 'html.parser')

    headings = []
    for level in ['h1', 'h2', 'h3', 'h4']:
        for tag in soup.find_all(level):
            text = tag.get_text(strip=True)
            if text:
                headings.append({'level': level, 'text': text})

    paragraphs = [
        p.get_text(strip=True)
        for p in soup.find_all('p')
        if p.get_text(strip=True) and len(p.get_text(strip=True)) > 10
    ]

    lists = []
    for ul in soup.find_all(['ul', 'ol']):
        items = [li.get_text(strip=True) for li in ul.find_all('li')]
        if items and len(items) < 50:  # Filtrar menús enormes
            lists.append({'type': ul.name, 'items': items})

    images = []
    seen_urls = set()
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
        if src and src not in seen_urls and not src.startswith('data:'):
            seen_urls.add(src)
            images.append({
                'src': src,
                'alt': img.get('alt', ''),
                'title': img.get('title', ''),
                'width': img.get('width', ''),
                'height': img.get('height', ''),
            })

    internal_links = []
    external_links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:'):
            continue
        link_data = {'url': href, 'text': a.get_text(strip=True)}
        if is_internal_link(href, base_domain):
            internal_links.append(link_data)
        else:
            external_links.append(link_data)

    buttons = []
    for btn in soup.find_all(class_=re.compile(r'btn|button|vc_btn|wd-button')):
        text = btn.get_text(strip=True)
        href = btn.get('href') or (btn.find('a').get('href') if btn.find('a') else None)
        if text and len(text) < 100:
            buttons.append({'text': text, 'href': href})

    embeds = []
    for iframe in soup.find_all('iframe'):
        src = iframe.get('src', '')
        if src:
            embed_type = 'unknown'
            if 'youtube' in src:
                embed_type = 'youtube'
            elif 'vimeo' in src:
                embed_type = 'vimeo'
            elif 'google.com/maps' in src:
                embed_type = 'google_maps'
            embeds.append({'type': embed_type, 'src': src})

    return {
        'headings': headings,
        'paragraphs': paragraphs,
        'lists': lists,
        'images': images,
        'internal_links': internal_links,
        'external_links': external_links,
        'buttons': buttons,
        'embeds': embeds,
    }


# ============================================================================
# DESCARGA DE IMÁGENES
# ============================================================================
def download_images(images: list, target_dir: Path) -> list:
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for i, img in enumerate(images, 1):
        src = img['src']
        try:
            ext = Path(urlparse(src).path).suffix.lower() or '.jpg'
            if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']:
                ext = '.jpg'
            filename = f"img-{i:02d}{ext}"
            filepath = target_dir / filename

            r = requests.get(src, stream=True, timeout=REQUEST_TIMEOUT,
                            headers={'User-Agent': USER_AGENT})
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)

            downloaded.append({
                **img,
                'local_path': f"media/{filename}",
                'filename': filename,
            })
            print(f"     📥 {filename}")
        except Exception as e:
            print(f"     ⚠️  Error descargando {src}: {e}")
            downloaded.append({**img, 'local_path': None, 'error': str(e)})

    return downloaded


# ============================================================================
# SCREENSHOTS
# ============================================================================
def take_screenshots(url: str, target_dir: Path) -> bool:
    if not PLAYWRIGHT_AVAILABLE:
        return False

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # Desktop
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(3000)  # Esperar lazy-loaded images
            page.screenshot(path=str(target_dir / 'screenshot-desktop.png'), full_page=True)
            context.close()
            print(f"     📸 desktop")

            # Mobile
            context = browser.new_context(viewport={'width': 375, 'height': 812})
            page = context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(target_dir / 'screenshot-mobile.png'), full_page=True)
            context.close()
            print(f"     📸 mobile")

            browser.close()
            return True
    except Exception as e:
        print(f"     ⚠️  Error en screenshots: {e}")
        return False


# ============================================================================
# GENERACIÓN HTML PREVIEW
# ============================================================================
def generate_html_preview(content: dict, metadata: dict, url: str, output_path: Path):
    """HTML legible para el diseñador."""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Migration Brief — {metadata.get('title', 'Sin título')}</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 1rem; color: #222; line-height: 1.6; background: #fff; }}
    h1 {{ border-bottom: 3px solid #2e7d32; padding-bottom: 0.5rem; }}
    h2 {{ color: #2e7d32; margin-top: 2rem; border-left: 4px solid #2e7d32; padding-left: 0.8rem; }}
    .meta-box {{ background: #f1f8e9; padding: 1rem; border-left: 4px solid #2e7d32; margin: 1rem 0; border-radius: 4px; }}
    .meta-box code {{ background: #fff; padding: 2px 6px; border-radius: 3px; font-size: 0.9rem; }}
    .priority-badge {{ display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: bold; font-size: 0.85rem; }}
    .priority-HIGH {{ background: #c62828; color: white; }}
    .priority-LOW {{ background: #757575; color: white; }}
    .heading-item {{ margin: 0.3rem 0; padding: 0.3rem 0.5rem; border-radius: 3px; }}
    .h1-tag {{ font-weight: bold; color: #c62828; background: #ffebee; }}
    .h2-tag {{ font-weight: bold; color: #1565c0; background: #e3f2fd; margin-left: 1rem; }}
    .h3-tag {{ color: #2e7d32; background: #e8f5e9; margin-left: 2rem; }}
    .h4-tag {{ color: #555; background: #f5f5f5; margin-left: 3rem; }}
    .image-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; margin: 1rem 0; }}
    .image-item {{ background: #fff; border: 1px solid #ddd; padding: 0.5rem; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
    .image-item img {{ max-width: 100%; height: auto; border-radius: 4px; }}
    .image-item .info {{ font-size: 0.85rem; color: #555; margin-top: 0.4rem; }}
    .link-table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem; }}
    .link-table th, .link-table td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
    .link-table th {{ background: #2e7d32; color: white; }}
    .link-table tr:nth-child(even) {{ background: #f9f9f9; }}
    .paragraph {{ background: #fafafa; padding: 0.8rem; margin: 0.5rem 0; border-radius: 4px; border-left: 3px solid #2e7d32; }}
    .button-pill {{ display: inline-block; background: #2e7d32; color: white; padding: 0.4rem 1rem; border-radius: 20px; margin: 0.3rem; font-weight: 500; }}
    .badge {{ display: inline-block; background: #e0e0e0; padding: 2px 8px; border-radius: 10px; font-size: 0.85rem; }}
    .stats {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }}
    .stat-item {{ background: #f5f5f5; padding: 0.5rem 1rem; border-radius: 6px; }}
    .stat-item strong {{ color: #2e7d32; }}
</style>
</head>
<body>

<h1>📋 Migration Brief</h1>
<h2 style="border:none; margin-top:0;">{metadata.get('title', 'Sin título')}</h2>

<div class="meta-box">
<span class="priority-badge priority-{metadata.get('priority', 'LOW')}">{metadata.get('priority', 'LOW')}</span>
<strong>URL original:</strong> <a href="{url}" target="_blank">{url}</a><br>
<strong>Slug (preservar exacto):</strong> <code>{metadata.get('slug', '')}</code><br>
<strong>Source path:</strong> <code>{metadata.get('source_path', '')}</code><br>
<strong>Tipo:</strong> {metadata.get('type', 'page')}<br>
<strong>Extracción:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}
</div>

<div class="stats">
    <div class="stat-item">📑 Headings: <strong>{len(content.get('headings', []))}</strong></div>
    <div class="stat-item">📝 Párrafos: <strong>{len(content.get('paragraphs', []))}</strong></div>
    <div class="stat-item">🖼️ Imágenes: <strong>{len(content.get('images', []))}</strong></div>
    <div class="stat-item">🔗 Enlaces internos: <strong>{len(content.get('internal_links', []))}</strong></div>
    <div class="stat-item">🔘 Botones: <strong>{len(content.get('buttons', []))}</strong></div>
</div>

<h2>📑 Estructura semántica (Headings SEO)</h2>
<p><em>Replica exactamente esta jerarquía en Elementor para preservar el SEO.</em></p>
"""

    for h in content.get('headings', []):
        css_class = f"{h['level']}-tag heading-item"
        html += f'<div class="{css_class}">[{h["level"].upper()}] {h["text"]}</div>\n'

    html += f"""
<h2>📝 Contenido textual</h2>
<p><em>{len(content.get('paragraphs', []))} párrafos detectados. Listos para copiar a widgets de texto.</em></p>
"""

    for i, p in enumerate(content.get('paragraphs', []), 1):
        html += f'<div class="paragraph"><strong>Párrafo {i}:</strong><br>{p}</div>\n'

    if content.get('lists'):
        html += '<h2>📋 Listas</h2>\n'
        for lst in content['lists']:
            html += f'<{lst["type"]}>\n'
            for item in lst['items']:
                html += f'<li>{item}</li>\n'
            html += f'</{lst["type"]}>\n'

    if content.get('images'):
        html += f'<h2>🖼️ Imágenes ({len(content["images"])})</h2>\n'
        html += '<p><em>Ya descargadas en <code>/media/</code>. Subir a la mediateca del staging.</em></p>\n'
        html += '<div class="image-grid">\n'
        for img in content['images']:
            local = img.get('local_path', '')
            alt = img.get('alt', 'Sin alt text')
            filename = img.get('filename', '')
            if local:
                html += f"""<div class="image-item">
                    <img src="{local}" alt="{alt}">
                    <div class="info">
                        <strong>Alt:</strong> {alt}<br>
                        <strong>Archivo:</strong> <code>{filename}</code>
                    </div>
                </div>\n"""
        html += '</div>\n'

    if content.get('buttons'):
        html += '<h2>🔘 Botones / CTAs</h2>\n'
        for btn in content['buttons']:
            html += f'<div><span class="button-pill">{btn["text"]}</span> → <code>{btn.get("href", "—")}</code></div>\n'

    if content.get('internal_links'):
        html += f'<h2>🔗 Enlaces internos ({len(content["internal_links"])})</h2>\n'
        html += '<p><em>Verificar que cada enlace exista y resuelva correctamente en el staging.</em></p>\n'
        html += '<table class="link-table"><tr><th>Anchor text</th><th>URL destino</th></tr>\n'
        for link in content['internal_links'][:50]:  # Limitar a 50
            html += f'<tr><td>{link["text"]}</td><td><code>{link["url"]}</code></td></tr>\n'
        html += '</table>\n'

    if content.get('external_links'):
        html += f'<h2>🌐 Enlaces externos ({len(content["external_links"])})</h2>\n'
        html += '<table class="link-table"><tr><th>Anchor text</th><th>URL</th></tr>\n'
        for link in content['external_links'][:30]:
            html += f'<tr><td>{link["text"]}</td><td><code>{link["url"]}</code></td></tr>\n'
        html += '</table>\n'

    if content.get('embeds'):
        html += f'<h2>🎥 Embeds ({len(content["embeds"])})</h2>\n'
        for emb in content['embeds']:
            html += f'<div><span class="badge">{emb["type"]}</span> <code>{emb["src"]}</code></div>\n'

    html += '</body></html>'
    output_path.write_text(html, encoding='utf-8')


# ============================================================================
# PROCESAMIENTO POR URL
# ============================================================================
def process_row(row: dict, output_base: Path, dry_run: bool = False):
    """Procesa una fila del CSV (una URL)."""
    source_path = row['source_path']
    priority = row.get('priority', 'LOW')
    url = build_full_url(source_path)

    print(f"\n{'='*65}")
    print(f"🔄 [{priority}] {source_path}")
    print(f"   URL: {url}")
    print(f"{'='*65}")

    if dry_run:
        print(f"   [DRY-RUN] Saltando procesamiento real.")
        return {'source_path': source_path, 'priority': priority, 'status': 'DRY_RUN'}

    # Crear directorio del kit (organizado por prioridad)
    priority_dir = output_base / priority.lower()
    kit_dir = priority_dir / slug_to_dirname(source_path)
    kit_dir.mkdir(parents=True, exist_ok=True)

    # 1. Intentar REST API
    print(f"   🔍 Intentando REST API...")
    post_data = fetch_via_rest_api(source_path)

    # 2. Fallback a HTML scraping
    if not post_data:
        print(f"   🔄 Fallback a HTML scraping...")
        post_data = fetch_via_html_scraping(url)

    if not post_data:
        print(f"   ❌ No se pudo obtener contenido")
        (kit_dir / 'ERROR.txt').write_text(
            f"No se pudo obtener contenido de {url}\n"
            f"Verificar:\n"
            f"1. La URL existe y es pública.\n"
            f"2. Las credenciales WP_USERNAME/WP_APP_PASSWORD son válidas.\n"
            f"3. El plugin 'Disable REST API' permite acceso autenticado."
        )
        return {'source_path': source_path, 'priority': priority, 'status': 'ERROR'}

    print(f"   ✅ Datos obtenidos vía: {post_data.get('_endpoint', 'unknown')}")

    # 3. Extraer contenido
    rendered = post_data.get('content', {}).get('rendered', '') if isinstance(post_data.get('content'), dict) else ''
    if not rendered and post_data.get('_raw_html'):
        rendered = post_data['_raw_html']

    base_domain = urlparse(SITE_ORIGEN).netloc
    content = parse_rendered_content(rendered, base_domain)

    # 4. Estructura WPBakery
    raw_content = post_data.get('content', {}).get('raw', rendered) if isinstance(post_data.get('content'), dict) else ''
    column_structure = extract_wpbakery_structure(raw_content)

    # 5. Descargar imágenes
    if content['images']:
        print(f"   📥 Descargando {len(content['images'])} imágenes...")
        content['images'] = download_images(content['images'], kit_dir / 'media')

    # 6. Screenshots
    if PLAYWRIGHT_AVAILABLE:
        print(f"   📸 Capturando screenshots...")
        take_screenshots(url, kit_dir)

    # 7. Metadata
    title = post_data.get('title', {}).get('rendered', '') if isinstance(post_data.get('title'), dict) else post_data.get('title', '')
    metadata = {
        'title': title,
        'slug': post_data.get('slug', ''),
        'source_path': source_path,
        'priority': priority,
        'is_sitelink': row.get('is_sitelink', 'False'),
        'type': post_data.get('_endpoint', 'unknown'),
        'date': post_data.get('date', ''),
        'modified': post_data.get('modified', ''),
        'url_original': url,
        'column_structure': column_structure,
    }

    # 8. Guardar archivos
    brief = {'metadata': metadata, 'content': content}

    (kit_dir / 'content-brief.json').write_text(
        json.dumps(brief, indent=2, ensure_ascii=False), encoding='utf-8'
    )
    (kit_dir / 'seo-metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8'
    )

    with open(kit_dir / 'internal-links.csv', 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['url', 'text'])
        writer.writeheader()
        writer.writerows(content['internal_links'])

    generate_html_preview(content, metadata, url, kit_dir / 'content-brief.html')

    print(f"   ✅ Kit completo: {kit_dir}")
    return {'source_path': source_path, 'priority': priority, 'status': 'OK', 'kit_dir': str(kit_dir)}


# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Migrator Co — Not Wood Edition')
    parser.add_argument('--priority', 
                        choices=['HIGH-CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'LEGAL', 'FUNCTIONAL', 'ALL'], 
                        default='HIGH-CRITICAL',
                        help='Qué URLs procesar (default: HIGH-CRITICAL)')
    parser.add_argument('--csv', default=CSV_MAPPING_PATH,
                        help='Path al CSV de mapeo')
    parser.add_argument('--output', default=OUTPUT_BASE,
                        help='Directorio de salida')
    parser.add_argument('--dry-run', action='store_true',
                        help='Solo listar qué procesaría, sin descargar')
    parser.add_argument('--include-homepage', action='store_true', default=True,
                        help='Incluir homepage (/) aunque no esté en el CSV')
    args = parser.parse_args()

    # Validar configuración
    if not args.dry_run:
        auth = get_auth_header()
        if not auth:
            print("⚠️  ATENCIÓN: WP_USERNAME y WP_APP_PASSWORD no configurados.")
            print("   El script usará scraping HTML como único método.")
            print("   Para mejor calidad, edita el script y agrega credenciales.\n")
            input("   Presiona ENTER para continuar con scraping HTML, o Ctrl+C para abortar... ")

    # Cargar CSV
    if not Path(args.csv).exists():
        print(f"❌ No se encontró el archivo: {args.csv}")
        sys.exit(1)

    rows = []
    with open(args.csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): (v.strip() if v else '') for k, v in row.items()}
            if row.get('source_path'):
                rows.append(row)

    # Agregar homepage si no está
    if args.include_homepage:
        has_home = any(r['source_path'] == '/' for r in rows)
        if not has_home:
            print("ℹ️  Agregando homepage (/) que falta en el CSV de mapping.")
            rows.insert(0, {
                'source_path': '/',
                'target_path_placeholder': '/',
                'rank_score': '0',
                'is_sitelink': 'True',
                'priority': 'HIGH',
            })

    # Filtrar por prioridad
    if args.priority == 'ALL':
        filtered = rows
    else:
        filtered = [r for r in rows if r.get('priority', '').upper() == args.priority]

    print(f"\n📊 RESUMEN DE EJECUCIÓN")
    print(f"   CSV: {args.csv}")
    print(f"   Total URLs en CSV: {len(rows)}")
    print(f"   Filtro: priority={args.priority}")
    print(f"   URLs a procesar: {len(filtered)}")
    print(f"   Output: {args.output}")
    print(f"   Modo: {'DRY-RUN' if args.dry_run else 'EJECUCIÓN REAL'}")
    print(f"   Playwright (screenshots): {'✅ disponible' if PLAYWRIGHT_AVAILABLE else '❌ no instalado'}")
    print()

    output_base = Path(args.output)
    output_base.mkdir(parents=True, exist_ok=True)

    summary = []
    for i, row in enumerate(filtered, 1):
        print(f"\n[{i}/{len(filtered)}]")
        try:
            result = process_row(row, output_base, dry_run=args.dry_run)
            summary.append(result)
        except KeyboardInterrupt:
            print("\n⛔ Interrumpido por usuario")
            break
        except Exception as e:
            print(f"   ❌ Error procesando: {e}")
            summary.append({
                'source_path': row.get('source_path', ''),
                'priority': row.get('priority', ''),
                'status': 'ERROR',
                'error': str(e)
            })

    # Resumen final
    summary_path = output_base / f'_resumen-{args.priority.lower()}.csv'
    with open(summary_path, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ['source_path', 'priority', 'status', 'kit_dir', 'error']
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(summary)

    ok = sum(1 for s in summary if s.get('status') == 'OK')
    err = sum(1 for s in summary if s.get('status') == 'ERROR')

    print(f"\n{'='*65}")
    print(f"✅ Proceso completado")
    print(f"   OK:     {ok}")
    print(f"   ERROR:  {err}")
    print(f"   Resumen: {summary_path}")
    print(f"{'='*65}")


if __name__ == '__main__':
    main()
    