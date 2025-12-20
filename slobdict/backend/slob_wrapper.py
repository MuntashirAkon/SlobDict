# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import tempfile
import shutil
from pathlib import Path

class SlobWrapper:
    """Wrapper to load slob files by copying to temp location."""
    
    def __init__(self, file_path):
        """Initialize slob wrapper with file path."""
        self.original_path = Path(file_path)
        
        # Create temp file with no-space name
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir) / "dict.slob"
        
        # Copy file
        shutil.copy2(str(self.original_path), str(self.temp_path))
        
        # Load with slob
        from .slob import Slob
        self.slob_obj = Slob(str(self.temp_path))
    
    def __iter__(self):
        """Iterate through entries in slob."""
        return iter(self.slob_obj)
    
    def close(self):
        """Close and cleanup temp files."""
        try:
            self.slob_obj.close()
        except:
            pass
        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass
    
    def __getattr__(self, name):
        """Delegate other attributes to slob object."""
        return getattr(self.slob_obj, name)
