import csv

input_file = 'rankmath_301_import.csv'
output_file = 'rankmath_pro_import.csv'

with open(input_file, 'r', encoding='utf-8') as f_in, \
     open(output_file, 'w', newline='', encoding='utf-8') as f_out:
    
    reader = csv.DictReader(f_in)
    writer = csv.writer(f_out)
    
    # Headers exactos que pide Rank Math PRO
    writer.writerow(['source', 'destination', 'type', 'status', 'matching'])
    
    for row in reader:
        src = row.get('source', '').strip()
        tgt = row.get('target', '').strip()
        if src and tgt:
            writer.writerow([src, tgt, '301', 'active', 'exact'])

print(f"✅ Listo. Usa '{output_file}' para importar en Rank Math PRO.")