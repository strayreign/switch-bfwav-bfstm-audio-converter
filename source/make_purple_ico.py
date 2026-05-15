"""Run this once to regenerate switch_purple.ico from switch_purple.png."""
import struct, io, os, sys
from PIL import Image

here = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(here, 'switch_purple.png')
out_path = os.path.join(here, 'switch_purple.ico')

src = Image.open(src_path).convert('RGBA')

def to_bmp32_ico(img):
    w, h = img.size
    img_flipped = img.transpose(Image.FLIP_TOP_BOTTOM)
    r_ch, g_ch, b_ch, a_ch = img_flipped.split()  # RGBA -> split correctly
    pixels = list(zip(b_ch.tobytes(), g_ch.tobytes(), r_ch.tobytes(), a_ch.tobytes()))  # BGRA order
    raw = bytes([v for p in pixels for v in p])
    row_bytes = ((w + 31) // 32) * 4
    and_mask = bytes(row_bytes * h)
    header = struct.pack('<IiiHHIIiiII', 40, w, h * 2, 1, 32, 0, len(raw), 0, 0, 0, 0)
    return header + raw + and_mask

def to_png(img):
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()

sizes = [16, 24, 32, 48, 64, 128, 256]
entries = []
for s in sizes:
    img = src.resize((s, s), Image.LANCZOS)
    data = to_png(img) if s == 256 else to_bmp32_ico(img)
    entries.append((s, data))

num = len(entries)
ico = struct.pack('<HHH', 0, 1, num)
offset = 6 + num * 16
for s, data in entries:
    ico += struct.pack('<BBBBHHII',
        s if s < 256 else 0, s if s < 256 else 0,
        0, 0, 1, 32, len(data), offset)
    offset += len(data)
for _, data in entries:
    ico += data

with open(out_path, 'wb') as f:
    f.write(ico)

print(f'Written {out_path}  ({len(ico)} bytes, {num} sizes)')
input('Press Enter to close.')
