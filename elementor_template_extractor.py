#!/usr/bin/env python3
"""
Elementor Template Extractor — Not Wood Edition
================================================
Extrae el JSON nativo de Elementor desde URLs YA MAQUETADAS en el
staging dev.not-wood.cl con WoodMart, para reutilizarlo como template
en URLs siguientes.

⭐ CASOS DE USO (ambos soportados):

ESCENARIO A — Templates de URLs YA creadas en staging hoy:
   Si dev.not-wood.cl ya tiene páginas maquetadas con WoodMart antes
   de empezar nuestra migración, podemos extraerlas como punto de partida.
   
ESCENARIO B — Templates de URLs que el diseñador MAQUETARÁ en FASE 2:
   Cuando el diseñador termine la primera URL "modelo" de cada categoría
   visual, extraerla como template para clonar a las hermanas.

USO:
    python elementor_template_extractor.py \\
        --url https://dev.not-wood.cl/sky-side-opcion-perfecta-para-cielos-protege-humedad/ \\
        --label "modelo-subpaginas-revestimientos"
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
from base64 import b64encode
from datetime import datetime

import requests


# ============================================================================
# CONFIGURACIÓN
# ============================================================================

STAGING_SITE = "https://dev.not-wood.cl"

# Credenciales del STAGING (Application Password generada en dev.not-wood.cl)
STAGING_USERNAME = "TU_USUARIO_STAGING"
STAGING_APP_PASSWORD = "xxxx xxxx xxxx xxxx xxxx xxxx"

OUTPUT_DIR = "templates_elementor"
REQUEST_TIMEOUT = 30
USER_AGENT = "Migrator-Co-Template-Extractor/1.0"


# ============================================================================
# UTILIDADES
# ============================================================================
def get_auth_header():
    if STAGING_USERNAME == "TU_USUARIO_STAGING" or STAGING_APP_PASSWORD.startswith("xxxx"):
        return None
    credentials = f"{STAGING_USERNAME}:{STAGING_APP_PASSWORD}"
    encoded = b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "User-Agent": USER_AGENT}


def url_to_slug(url: str) -> str:
    path = urlparse(url).path.strip('/')
    return path.split('/')[-1] if path else 'home'


# ============================================================================
# EXTRACCIÓN
# ============================================================================
def get_post_by_slug(slug: str, headers: dict) -> dict:
    api_base = f"{STAGING_SITE}/wp-json/wp/v2"
    for endpoint in ['pages', 'posts']:
        try:
            r = requests.get(
                f"{api_base}/{endpoint}",
                params={'slug': slug, '_fields': 'id,title,slug,modified'},
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return {**data[0], '_endpoint': endpoint}
        except Exception as e:
            print(f"   ⚠️  Error consultando {endpoint}: {e}")
    return None


def get_elementor_data(post_id: int, endpoint: str, headers: dict) -> dict:
    try:
        r = requests.get(
            f"{STAGING_SITE}/wp-json/wp/v2/{endpoint}/{post_id}",
            params={'context': 'edit'},
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        data = r.json()

        meta = data.get('meta', {})
        elementor_data_raw = meta.get('_elementor_data', '') if isinstance(meta, dict) else ''

        if not elementor_data_raw:
            return {'success': False, 'reason': 'Página sin _elementor_data. ¿Está maquetada con Elementor?'}

        try:
            elementor_json = json.loads(elementor_data_raw) if isinstance(elementor_data_raw, str) else elementor_data_raw
        except json.JSONDecodeError:
            return {'success': False, 'reason': '_elementor_data no es JSON válido.'}

        return {
            'success': True,
            'elementor_data': elementor_json,
            'elementor_version': meta.get('_elementor_version', ''),
            'elementor_edit_mode': meta.get('_elementor_edit_mode', ''),
            'elementor_page_settings': meta.get('_elementor_page_settings', {}),
            'elementor_template_type': meta.get('_elementor_template_type', 'wp-page'),
            'post_id': post_id,
            'post_title': data.get('title', {}).get('rendered', ''),
            'post_slug': data.get('slug', ''),
            'modified': data.get('modified', ''),
        }
    except Exception as e:
        return {'success': False, 'reason': f'Error: {e}'}


def analyze_template(elementor_data: list) -> dict:
    stats = {
        'sections': 0,
        'columns': 0,
        'widgets_total': 0,
        'widgets_by_type': {},
        'images_referenced': set(),
        'woodmart_widgets': set(),
    }

    def traverse(elements):
        for el in elements:
            el_type = el.get('elType', '')
            if el_type == 'section':
                stats['sections'] += 1
            elif el_type == 'column':
                stats['columns'] += 1
            elif el_type == 'widget':
                stats['widgets_total'] += 1
                widget_type = el.get('widgetType', 'unknown')
                stats['widgets_by_type'][widget_type] = stats['widgets_by_type'].get(widget_type, 0) + 1
                if widget_type.startswith('wd_') or widget_type.startswith('woodmart'):
                    stats['woodmart_widgets'].add(widget_type)
                extract_image_urls(el.get('settings', {}), stats['images_referenced'])
            inner = el.get('elements', [])
            if inner:
                traverse(inner)

    traverse(elementor_data)
    stats['images_referenced'] = sorted(list(stats['images_referenced']))
    stats['woodmart_widgets'] = sorted(list(stats['woodmart_widgets']))
    return stats


def extract_image_urls(settings: dict, images_set: set):
    if not isinstance(settings, dict):
        return
    for key, value in settings.items():
        if isinstance(value, dict):
            url = value.get('url', '')
            if url and url.startswith('http') and any(
                url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']
            ):
                images_set.add(url)
            extract_image_urls(value, images_set)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    extract_image_urls(item, images_set)
        elif isinstance(value, str) and value.startswith('http'):
            if any(value.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']):
                images_set.add(value)


# ============================================================================
# OUTPUTS
# ============================================================================
def generate_importable_template(elementor_data, template_info, output_path):
    importable = {
        "version": "0.4",
        "title": template_info.get('post_title', 'Template'),
        "type": "page",
        "content": elementor_data,
        "page_settings": template_info.get('elementor_page_settings', {}) or {},
    }
    output_path.write_text(json.dumps(importable, indent=2, ensure_ascii=False), encoding='utf-8')


def generate_full_template(template_info, stats, output_path):
    full = {
        'extracted_at': datetime.now().isoformat(),
        'source_url': template_info.get('source_url', ''),
        'template_info': {k: v for k, v in template_info.items() if k != 'elementor_data'},
        'statistics': {**stats, 'images_referenced': list(stats['images_referenced']),
                       'woodmart_widgets': list(stats['woodmart_widgets'])},
        'elementor_data': template_info.get('elementor_data', []),
    }
    output_path.write_text(json.dumps(full, indent=2, ensure_ascii=False), encoding='utf-8')


def generate_readme(template_info, stats, label, output_path):
    md = f"""# 📐 Template Elementor — {label}

## ℹ️ Información

- **URL fuente:** {template_info.get('source_url', '')}
- **Página origen:** {template_info.get('post_title', '')}
- **Slug:** `{template_info.get('post_slug', '')}`
- **Versión Elementor:** {template_info.get('elementor_version', '—')}
- **Última modificación:** {template_info.get('modified', '—')}
- **Extraído:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

## 📊 Estadísticas

- 📦 Secciones: **{stats['sections']}**
- 📐 Columnas: **{stats['columns']}**
- 🧩 Widgets totales: **{stats['widgets_total']}**
- 🖼️ Imágenes referenciadas: **{len(stats['images_referenced'])}**
- ⭐ Widgets WoodMart: **{len(stats['woodmart_widgets'])}**

### Widgets utilizados

"""
    for widget_type, count in sorted(stats['widgets_by_type'].items(), key=lambda x: -x[1]):
        flag = ' ⭐' if widget_type.startswith('wd_') or widget_type.startswith('woodmart') else ''
        md += f"- `{widget_type}`: {count} uso(s){flag}\n"

    md += f"""

## 🚀 Cómo importar

### Opción A — Librería global Elementor (RECOMENDADO)

1. `dev.not-wood.cl/wp-admin/`
2. **Templates → Saved Templates**
3. Click **"Import Templates"**
4. Subir `{label}.json`
5. Aparece en la librería

### Opción B — A una página específica

1. Editar página destino → **"Edit with Elementor"**
2. En el lienzo, click ícono **📂 (carpeta)**
3. Pestaña **"My Templates"** → buscar `{label}`
4. Click **"Insert"**

### Después de aplicar

✅ **Personalizar según el brief del Migrator Co:**
- Reemplazar texto siguiendo `content-brief.html`
- Reemplazar imágenes desde `/media/` del kit
- Actualizar enlaces según `internal-links.csv`

⚠️ **NO cambiar:**
- Jerarquía de headings (H1 → H2 → H3)
- Slug de la página (debe coincidir con `source_path`)

## 🖼️ Imágenes de la página modelo

Reemplazar al aplicar a una URL nueva:

"""
    for i, img in enumerate(stats['images_referenced'], 1):
        md += f"{i}. `{img}`\n"

    if stats['woodmart_widgets']:
        md += "\n## ⚠️ Widgets WoodMart usados\n\n"
        for w in stats['woodmart_widgets']:
            md += f"- `{w}`\n"
        md += "\nVerificar que el plugin WoodMart esté activo antes de importar.\n"

    md += f"""

## 📦 Archivos generados

- `{label}.json` → **Template importable a Elementor**
- `{label}-full.json` → Datos completos (auditoría)
- `{label}-README.md` → Este archivo
- `{label}-images.txt` → URLs de imágenes

---

**Generado:** elementor_template_extractor.py — Migrator Co
"""
    output_path.write_text(md, encoding='utf-8')


def generate_images_list(images, output_path):
    output_path.write_text('\n'.join(images), encoding='utf-8')


# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Elementor Template Extractor — Not Wood')
    parser.add_argument('--url', required=True, help='URL del staging ya maquetada')
    parser.add_argument('--label', required=True, help='Etiqueta corta del template')
    parser.add_argument('--output-dir', default=OUTPUT_DIR, help='Directorio de salida')
    args = parser.parse_args()

    headers = get_auth_header()
    if not headers:
        print("❌ Configura STAGING_USERNAME y STAGING_APP_PASSWORD.")
        print("   Credenciales del STAGING (dev.not-wood.cl), NO de producción.")
        sys.exit(1)

    if 'dev.not-wood.cl' not in args.url:
        print(f"⚠️  URL no parece ser del staging: {args.url}")
        print(f"   ¿Continuar? (s/N): ", end='')
        if input().strip().lower() != 's':
            sys.exit(0)

    slug = url_to_slug(args.url)
    print(f"\n🔍 Buscando página: {slug}")

    post = get_post_by_slug(slug, headers)
    if not post:
        print(f"❌ No encontrada en {STAGING_SITE}")
        sys.exit(1)

    print(f"   ✓ Encontrada: '{post.get('title', {}).get('rendered', '')}' (ID: {post['id']})")

    print(f"\n📥 Extrayendo Elementor data...")
    template_info = get_elementor_data(post['id'], post['_endpoint'], headers)

    if not template_info.get('success'):
        print(f"❌ {template_info.get('reason', 'Error desconocido')}")
        sys.exit(1)

    template_info['source_url'] = args.url
    print(f"   ✓ Versión Elementor: {template_info.get('elementor_version', '—')}")

    print(f"\n📊 Analizando estructura...")
    stats = analyze_template(template_info['elementor_data'])
    print(f"   ✓ {stats['sections']} secciones | {stats['columns']} columnas | {stats['widgets_total']} widgets")
    print(f"   ✓ {len(stats['images_referenced'])} imágenes | {len(stats['woodmart_widgets'])} tipos WoodMart")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    label = args.label

    generate_importable_template(template_info['elementor_data'], template_info, output_dir / f'{label}.json')
    print(f"\n✅ {output_dir / f'{label}.json'}")

    generate_full_template(template_info, stats, output_dir / f'{label}-full.json')
    print(f"✅ {output_dir / f'{label}-full.json'}")

    generate_readme(template_info, stats, label, output_dir / f'{label}-README.md')
    print(f"✅ {output_dir / f'{label}-README.md'}")

    generate_images_list(stats['images_referenced'], output_dir / f'{label}-images.txt')
    print(f"✅ {output_dir / f'{label}-images.txt'}")

    print(f"\n{'='*65}")
    print(f"🎉 Template '{label}' extraído")
    print(f"{'='*65}")
    print(f"\n💡 Próximo paso:")
    print(f"   Compartir carpeta '{output_dir}' con el diseñador")
    print(f"   Él importa '{label}.json' en Elementor → aplica a URLs hermanas\n")


if __name__ == '__main__':
    main()
