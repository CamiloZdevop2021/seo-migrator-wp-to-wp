#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import json
import csv
import re
import os

# ================= CONFIGURACIÓN =================
XML_FILES = ['sitemap-1.xml', 'sitemap-2.xml', 'sitemap-3.xml']  # Tus 3 sitemaps
JSON_FILE = 'rankmath_export.json'  # Tu export de Rank Math
SITELINKS_FILE = 'sitelinks.txt'  # El archivo que ya tienes
IMPORT_CSV = 'rankmath_301_import.csv'  # Output para Rank Math
REFERENCE_CSV = 'url_mapping_reference.csv'  # Tu hoja de ruta
# ================================================

def parse_xml_sitemaps():
    urls = set()
    for f in XML_FILES:
        if not os.path.exists(f): 
            print(f"⚠️ {f} no encontrado, saltando...")
            continue
        try:
            tree = ET.parse(f)
            for loc in tree.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                url = loc.text.strip().rstrip('/')
                urls.add(url)
        except Exception as e:
            print(f"⚠️ Error leyendo {f}: {e}")
    return urls

def parse_rankmath_json():
    scores = {}
    if not os.path.exists(JSON_FILE): 
        print(f"⚠️ {JSON_FILE} no encontrado")
        return scores
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            items = data if isinstance(data, list) else data.get('posts', data.get('data', []))
            for item in items:
                url = (item.get('url') or item.get('permalink') or '').strip().rstrip('/')
                score = int(item.get('score') or item.get('rank_math_score') or item.get('seo_score') or 0)
                if url:
                    scores[url] = score
    except Exception as e:
        print(f"⚠️ Error leyendo JSON: {e}")
    return scores

def parse_sitelinks():
    links = set()
    if os.path.exists(SITELINKS_FILE):
        with open(SITELINKS_FILE, 'r', encoding='utf-8') as f:
            links = {line.strip().rstrip('/') for line in f if line.strip() and not line.startswith('#')}
        print(f"✅ {len(links)} sitelinks cargados desde {SITELINKS_FILE}")
    else:
        print(f"ℹ️ {SITELINKS_FILE} no encontrado → priorizando solo por Rank Math Score")
    return links

def get_priority(url, score, is_sitelink):
    if is_sitelink or score >= 85:
        return 'HIGH'
    elif score >= 60:
        return 'MEDIUM'
    else:
        return 'LOW'

def main():
    print("🔍 Parseando sitemaps XML...")
    urls = parse_xml_sitemaps()
    print(f"📦 {len(urls)} URLs extraídas de sitemaps")
    
    print("📊 Parseando Rank Math JSON...")
    scores = parse_rankmath_json()
    print(f"⭐ {len(scores)} scores cargados")
    
    print("🔗 Cargando sitelinks...")
    sitelinks = parse_sitelinks()
    
    rows_import = []
    rows_ref = []

    for url in sorted(urls):
        # Extrae path y normaliza
        path = re.sub(r'^https?://[^/]+', '', url)
        path = path if path != '' else '/'  # Corrige homepage vacía
        path = path.rstrip('/') if path != '/' else path  # Mantiene '/' para root
        
        score = scores.get(url, 0)
        is_sitelink = url in sitelinks
        priority = get_priority(url, score, is_sitelink)
        
        # Evita duplicar la homepage vacía
        if path == '' and url != '': 
            path = '/'
            
        rows_import.append([path, path, 301, 1, 0])
        rows_ref.append([path, path, score, is_sitelink, priority])

    # CSV para importar a Rank Math
    with open(IMPORT_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['source', 'target', 'status', 'enabled', 'regex'])
        w.writerows(rows_import)
    
    # CSV de referencia para tu mapeo de contenido
    with open(REFERENCE_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['source_path', 'target_path_placeholder', 'rank_score', 'is_sitelink', 'priority'])
        w.writerows(rows_ref)

    print(f"\n✅ {IMPORT_CSV} generado con {len(rows_import)} reglas listas para Rank Math.")
    print(f"📊 {REFERENCE_CSV} generado para priorizar migración de contenido.")
    high = sum(1 for r in rows_ref if r[4]=='HIGH')
    medium = sum(1 for r in rows_ref if r[4]=='MEDIUM')
    print(f"🎯 URLs HIGH: {high} | MEDIUM: {medium} | LOW: {len(rows_ref)-high-medium}")
    print("\n👉 Próximo paso: Migra contenido HIGH/MEDIUM a staging, actualiza 'target' si cambia la estructura, y re-ejecuta update_import.py")

if __name__ == '__main__':
    main()