import os, re, glob
import pandas as pd
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

ocr = RapidOCR()
train_df = pd.read_csv('data/claims_train.csv')
test_df = pd.read_csv('data/claims_test.csv')

raw_files = os.listdir('images')
file_map = {}
for f in raw_files:
    m = re.match(r'^[0-9a-fA-F-]{37}(.+)$', f)
    base = m.group(1) if m else f
    file_map[base] = f
    base_no_ext = os.path.splitext(base)[0]
    file_map[base_no_ext] = f

def get_path(img_name):
    if pd.isna(img_name):
        return None
    base = os.path.basename(str(img_name).replace('\\', '/').strip())
    if base in file_map:
        return os.path.join('images', file_map[base])
    stem = os.path.splitext(base)[0]
    if stem in file_map:
        return os.path.join('images', file_map[stem])
    return None

# Pick 35 varied claims across categories, statuses, and types
selected = [
    # Non approved in train
    'CLM-30856', 'CLM-30886', 'CLM-30979', 'CLM-31009', 'CLM-31079',
    # Fuel in train (thermal slips, BPCL, HPCL, IndianOil)
    'CLM-30421', 'CLM-30424', 'CLM-30425', 'CLM-30432', 'CLM-30446',
    # Food in train (restaurants, dhabas, tea snacks, printed tax invoices vs handwritten pads)
    'CLM-30412', 'CLM-30416', 'CLM-30428', 'CLM-30435', 'CLM-30436', 'CLM-30454', 'CLM-30465', 'CLM-30469',
    # Lodging in train (hotels, GST invoices, multi-night folios)
    'CLM-30418', 'CLM-30492', 'CLM-30509', 'CLM-30533', 'CLM-30681',
    # Local travel in train (cabs, handwritten slips, tours)
    'CLM-30472', 'CLM-30506', 'CLM-30524',
    # Courier in train (Vidarbha Express, Speedlink, Prompt Parcel)
    'CLM-30437', 'CLM-30508', 'CLM-30528', 'CLM-30679',
    # Parking in train
    'CLM-30458', 'CLM-30475', 'CLM-30494',
    # Test claims (fuel, food, lodging, courier, cab, parking, duplicate)
    'CLM-31086', 'CLM-31087', 'CLM-31094', 'CLM-31095', 'CLM-31111', 'CLM-31148', 'CLM-31475', 'CLM-31480'
]

print(f"Analyzing {len(selected)} varied images with RapidOCR...")
results = []
for cid in selected:
    # check train or test
    t_row = train_df[train_df['claim_id'] == cid]
    if len(t_row) > 0:
        row = t_row.iloc[0]
        split = 'train'
        status = row['status']
        clerk_note = str(row['clerk_note'])
    else:
        row = test_df[test_df['claim_id'] == cid].iloc[0]
        split = 'test'
        status = 'test'
        clerk_note = ''
    
    img_path = get_path(row['image_file'])
    if not img_path or not os.path.exists(img_path):
        results.append((cid, split, row['category'], row['vendor'], 'FILE_NOT_FOUND', 0, 0, []))
        continue
    
    with Image.open(img_path) as im:
        w, h = im.size
    
    ocr_res, _ = ocr(img_path)
    ocr_lines = [line[1] for line in ocr_res] if ocr_res else []
    results.append((cid, split, row['category'], row['vendor'], os.path.basename(img_path), w, h, ocr_lines[:6]))

for r in results:
    print(f"[{r[0]}] ({r[1]} | {r[2]} | {r[3]}) - {r[5]}x{r[6]} - Lines: {len(r[7])}")
    for l in r[7][:3]:
        print(f"    > {l}")
