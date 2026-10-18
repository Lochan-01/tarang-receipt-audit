import os
import re
import hashlib
from pathlib import Path
from typing import Optional, Tuple, Dict
from tarang.config import IMAGES_DIR

class ImageResolver:
    """
    Robust resolver for receipt images that handles:
    - Preceding device file paths (/storage/emulated/0/...)
    - Telegram export UUID prefixes (e.g. 07b39850-0519-4ec5-a03c-23403dab217c-IMG...)
    - .jpeg vs .jpg file extension differences
    """
    def __init__(self, images_dir: Path = IMAGES_DIR):
        self.images_dir = Path(images_dir)
        self._index: Dict[str, str] = {}
        self._hash_cache: Dict[str, str] = {}
        self._build_index()

    def _build_index(self):
        if not self.images_dir.exists():
            return
        for fname in os.listdir(self.images_dir):
            full_path = self.images_dir / fname
            if not full_path.is_file():
                continue
            # Exact filename
            self._index[fname.lower()] = fname
            
            # Match UUID prefix: 36 hex/dash chars + '-'
            m = re.match(r'^[0-9a-fA-F-]{37}(.+)$', fname)
            if m:
                base_name = m.group(1).lower()
                self._index[base_name] = fname
                stem = os.path.splitext(base_name)[0]
                self._index[f"stem:{stem}"] = fname
            else:
                stem = os.path.splitext(fname.lower())[0]
                self._index[f"stem:{stem}"] = fname

    def resolve(self, raw_input: Optional[str]) -> Tuple[Optional[Path], Optional[str]]:
        """
        Given a raw image_file string from CSV or user upload:
        Returns: (resolved_path, error_reason)
        """
        if not raw_input or not isinstance(raw_input, str) or not raw_input.strip():
            return None, "No image filename provided"

        # 0. Check if direct file path exists
        try:
            direct_p = Path(raw_input)
            if direct_p.is_file():
                return direct_p, None
        except Exception:
            pass

        # 1. Clean path (handle windows & posix slashes)
        clean = os.path.basename(raw_input.replace('\\', '/').strip()).lower()

        # 2. Check exact or stripped match
        if clean in self._index:
            return self.images_dir / self._index[clean], None

        # 3. Check stem match (.jpeg <-> .jpg)
        stem = os.path.splitext(clean)[0]
        stem_key = f"stem:{stem}"
        if stem_key in self._index:
            return self.images_dir / self._index[stem_key], None

        return None, f"Image file '{raw_input}' not found on server (upload failure)"

    def compute_sha256(self, file_path: Path) -> str:
        """Computes and caches SHA256 of the image file."""
        p_str = str(file_path.resolve())
        if p_str in self._hash_cache:
            return self._hash_cache[p_str]
        
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        self._hash_cache[p_str] = digest
        return digest
