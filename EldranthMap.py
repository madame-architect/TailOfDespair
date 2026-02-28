## Why you got that error

Your environment does not have the **DejaVu** TTFs in the Linux paths I hardcoded. The script intentionally fails fast if it cannot locate a usable `.ttf`.

## Fix options (pick one)

### Option A (recommended): Add a robust font resolver (cross-platform)

Replace the `find_font(...)` function and the font-loading block with the version below. It:

* Checks common Linux, macOS, Windows font locations
* Uses `matplotlib.font_manager` if available (optional)
* Falls back to PIL’s default bitmap font as a last resort (still runs, but typography is less nice)

#### Patch: drop-in replacement

```python
import os
import sys
from typing import List, Optional

from PIL import ImageFont

def _candidate_font_paths() -> List[str]:
    """Common font paths across Linux/macOS/Windows."""
    paths: List[str] = []

    # Linux
    paths += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    # macOS
    paths += [
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Times New Roman.ttf",
        "/Library/Fonts/Georgia.ttf",
    ]

    # Windows (best effort, if script is run on Windows)
    win = os.environ.get("WINDIR", r"C:\Windows")
    paths += [
        os.path.join(win, "Fonts", "timesbd.ttf"),  # Times New Roman Bold
        os.path.join(win, "Fonts", "times.ttf"),    # Times New Roman
        os.path.join(win, "Fonts", "georgiab.ttf"), # Georgia Bold
        os.path.join(win, "Fonts", "georgia.ttf"),  # Georgia
        os.path.join(win, "Fonts", "arial.ttf"),    # Arial
        os.path.join(win, "Fonts", "calibri.ttf"),  # Calibri
    ]

    return paths


def find_font(preferred_names: Optional[List[str]] = None) -> Optional[str]:
    """
    Try to locate a usable TrueType font file.
    Returns a path or None if nothing found.
    """
    # 1) Explicit preferred paths
    for p in _candidate_font_paths():
        if os.path.exists(p):
            return p

    # 2) If matplotlib is installed, use its font discovery (optional dependency)
    try:
        from matplotlib import font_manager
        # Try preferred names first, then a generic serif/sans
        names = preferred_names or ["DejaVu Serif", "DejaVu Sans", "Liberation Serif", "Times New Roman", "Georgia", "Arial"]
        for name in names:
            try:
                fp = font_manager.findfont(name, fallback_to_default=False)
                if fp and os.path.exists(fp) and fp.lower().endswith((".ttf", ".otf")):
                    return fp
            except Exception:
                pass
        # Try default font
        fp = font_manager.findfont(font_manager.FontProperties(), fallback_to_default=True)
        if fp and os.path.exists(fp) and fp.lower().endswith((".ttf", ".otf")):
            return fp
    except Exception:
        pass

    return None


def load_font(size: int, preferred_names: Optional[List[str]] = None) -> ImageFont.ImageFont:
    """
    Load a TTF font if possible; otherwise fall back to PIL's default font.
    """
    fp = find_font(preferred_names=preferred_names)
    if fp:
        return ImageFont.truetype(fp, size)
    # Last resort: bitmap default (no TTF available)
    return ImageFont.load_default()
```

Then replace your font loading lines with:

```python
font_district = load_font(54, preferred_names=["DejaVu Serif", "Liberation Serif", "Times New Roman", "Georgia"])
font_poi      = load_font(34, preferred_names=["DejaVu Serif", "Liberation Serif", "Times New Roman", "Georgia"])
font_small    = load_font(28, preferred_names=["DejaVu Sans", "Liberation Sans", "Arial", "Calibri"])
font_title    = load_font(78, preferred_names=["DejaVu Serif", "Liberation Serif", "Times New Roman", "Georgia"])
```

This will run on most machines without you having to install anything.

---

### Option B: Install fonts (Linux)

If you are on Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y fonts-dejavu-core
```

Then keep the original DejaVu paths.

---

### Option C: Provide your own font files

Place `.ttf` files in the same folder as the script (for example `./fonts/`) and hardcode them:

```python
font_district = ImageFont.truetype("./fonts/YourSerifBold.ttf", 54)
```

---

## Practical note (Roll20)

If you are generating the **6144px JPG**, font outlines at large sizes look best with true TTF/OTF. The PIL default font will “work,” but the map labels will look noticeably less polished.

If you tell me your OS (Windows/macOS/Linux) and how you are running the script (local Python, Docker, etc.), I can give you the shortest exact install command or a minimal font folder approach.
