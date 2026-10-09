import numpy as np
from PIL import Image, ImageFilter
SRC = "docs/brand/logo-source.png"
OUT = "custom_components/ha_flightseats/brand/"
im = Image.open(SRC).convert("RGB")
a = np.asarray(im)
near_white = a.min(axis=2) > 225

# Exterior = near-white pixels connected to the border. Thin white features (the stem,
# outlines) are removed by a morphological opening first, so the white circles inside
# the house stay opaque instead of leaking out to the background.
def propagate(seed, allowed, max_iter=None):
    cur = seed.copy(); i = 0
    while True:
        grown = cur.copy()
        grown[1:, :] |= cur[:-1, :]; grown[:-1, :] |= cur[1:, :]
        grown[:, 1:] |= cur[:, :-1]; grown[:, :-1] |= cur[:, 1:]
        grown &= allowed
        i += 1
        if (grown == cur).all() or (max_iter and i >= max_iter):
            return grown
        cur = grown

nw_img = Image.fromarray(np.where(near_white, 255, 0).astype("uint8"))
opened = nw_img.filter(ImageFilter.MinFilter(31)).filter(ImageFilter.MaxFilter(31))
opened = np.asarray(opened) > 127
opened[950:] = near_white[950:]  # no opening on the wordmark: keep the gaps between letters
border = np.zeros_like(near_white)
border[0, :] = border[-1, :] = True; border[:, 0] = border[:, -1] = True
ext_core = propagate(border & opened, opened)
ext = propagate(ext_core, near_white, max_iter=30)
print("exterior fraction", round(ext.mean(), 3))

opaque = Image.fromarray(np.where(ext, 0, 255).astype("uint8"))
opaque = opaque.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.9))
rgba = Image.fromarray(a).convert("RGBA"); rgba.putalpha(opaque)

def square_crop(img, y_max=None, pad=0.05):
    if y_max:
        img = img.crop((0, 0, img.width, y_max))
    al = np.asarray(img.split()[3])
    ys, xs = np.where(al > 20)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    side = int(max(x1 - x0, y1 - y0) * (1 + 2 * pad))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    left, top = cx - side // 2, cy - side // 2
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, (-left, -top))
    return canvas

# the symbol ends at row ~917 and the wordmark starts at ~985
icon = square_crop(rgba, y_max=950)
logo = square_crop(rgba)

def darken(img):
    arr = np.asarray(img).astype(float)
    navy = np.array([8, 42, 83.])
    k = np.clip(1 - np.linalg.norm(arr[..., :3] - navy, axis=2) / 110, 0, 1)[..., None]
    arr[..., :3] = arr[..., :3] * (1 - k) + 255 * k
    return Image.fromarray(arr.astype("uint8"), "RGBA")

def save(img, name, size):
    img.resize((size, size), Image.LANCZOS).save(OUT + name, optimize=True)

for name, img in (("icon", icon), ("logo", logo), ("dark_icon", darken(icon)), ("dark_logo", darken(logo))):
    save(img, name + ".png", 256)
    save(img, name + "@2x.png", 512)

def L(n): return Image.open(OUT + n).convert("RGBA")
s = Image.new("RGBA", (1024, 380), (255, 255, 255, 255))
s.alpha_composite(Image.new("RGBA", (512, 380), (24, 28, 32, 255)), (512, 0))
for n, pos in (("icon@2x.png", (10, 10)), ("logo@2x.png", (260, 10)), ("dark_icon@2x.png", (522, 10)), ("dark_logo@2x.png", (772, 10))):
    s.alpha_composite(L(n).resize((240, 240)), pos)
s.alpha_composite(L("icon.png").resize((64, 64)), (10, 280)); s.alpha_composite(L("dark_icon.png").resize((64, 64)), (522, 280))
s.save("/tmp/brand_preview.png")
