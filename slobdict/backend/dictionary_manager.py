# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
import json


class DictionaryManager:
    """Manages dictionary files and metadata with automatic format conversion."""

    def __init__(self) -> None:
        """Initialize dictionary manager."""
        from ..utils.utils import get_config_dir
        self.config_dir = get_config_dir()
        self.dicts_dir = self.config_dir / "dictionaries"
        self.metadata_file = self.config_dir / "dictionaries.json"
        
        # Create directories if they don't exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.dicts_dir.mkdir(parents=True, exist_ok=True)
        
        # Load metadata
        self.metadata = self._load_metadata()
        
        # Initialize PyGlossary once
        self._init_pyglossary()

    def _init_pyglossary(self) -> bool:
        """
        Initialize PyGlossary for dictionary conversion.
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            from pyglossary.glossary_v2 import Glossary
            Glossary.init()
            self._pyglossary_available = True
            return True
        except ImportError:
            print("Warning: PyGlossary not installed. Install with: pip install pyglossary")
            print("Dictionary conversion will not be available.")
            self._pyglossary_available = False
            return False

    def _load_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Load dictionary metadata from file."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    metadata: Dict[str, Dict[str, Any]] = json.load(f)
                    return metadata
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_metadata(self) -> None:
        """Save dictionary metadata to file."""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)

    def _validate_input_source(self, source_path: str) -> Path:
        """
        Validate that input source exists and is accessible.
        
        Args:
            source_path: Path to dictionary file or directory
            
        Returns:
            Validated Path object
            
        Raises:
            FileNotFoundError: If source doesn't exist
            ValueError: If source is not readable
        """
        source = Path(source_path).resolve()
        
        if not source.exists():
            raise FileNotFoundError(f"Source not found: {source_path}")
        
        if source.is_file():
            if source.stat().st_size == 0:
                raise ValueError(f"Source file is empty: {source_path}")
            try:
                with open(source, 'rb') as f:
                    f.read(1)
            except PermissionError:
                raise PermissionError(f"Permission denied reading file: {source_path}")
        elif source.is_dir():
            # For directories, check if readable
            try:
                list(source.iterdir())
            except PermissionError:
                raise PermissionError(f"Permission denied accessing directory: {source_path}")
        else:
            raise ValueError(f"Source is neither a file nor directory: {source_path}")
        
        return source

    def _convert_to_slob(
        self,
        source_path: Path,
        dest_path: Path,
        source_format: Optional[str] = None
    ) -> bool:
        """
        Convert a dictionary file/directory to SLOB format.
        
        Args:
            source_path: Path to source dictionary file or directory
            dest_path: Path to destination SLOB file
            source_format: Optional PyGlossary format name (e.g., 'StarDict', 'MDict')
            
        Returns:
            True if conversion successful
            
        Raises:
            RuntimeError: If conversion fails
        """
        if not self._pyglossary_available:
            raise RuntimeError("PyGlossary not available for conversion")
        
        try:
            from pyglossary.glossary_v2 import ConvertArgs, Glossary
            
            # Get size info for logging
            if source_path.is_file():
                file_size = source_path.stat().st_size
                file_size_mb = file_size / (1024 * 1024)
                size_info = f"({file_size_mb:.2f} MB)"
            else:
                size_info = "(directory)"
            
            format_info = f" [{source_format}]" if source_format else ""
            print(f"Converting {source_path.name} {size_info}{format_info} to SLOB...")
            
            glos = Glossary()
            
            # Build ConvertArgs
            inputFormat = "" if source_format is None else source_format
            convert_args = ConvertArgs(
                inputFilename=str(source_path),
                inputFormat=inputFormat,
                outputFilename=str(dest_path),
                outputFormat="Aard2Slob",
                sqlite=True,  # Use SQLite for memory efficiency
            )

            glos.convert(convert_args)
            
            output_size = dest_path.stat().st_size
            output_size_mb = output_size / (1024 * 1024)
            print(f"Conversion complete. Output: {output_size_mb:.2f} MB")
            
            return True
            
        except Exception as e:
            # Clean up partial output file
            try:
                if dest_path.exists():
                    dest_path.unlink()
            except Exception:
                pass
            raise

    def _copy_slob_file(self, source_path: Path, dest_path: Path) -> bool:
        """
        Copy a SLOB file directly (no conversion needed).
        
        Args:
            source_path: Path to source SLOB file
            dest_path: Path to destination SLOB file
            
        Returns:
            True if copy successful
            
        Raises:
            IOError: If copy fails
        """
        try:
            shutil.copy2(source_path, dest_path)
            
            # Verify copy integrity
            if source_path.stat().st_size != dest_path.stat().st_size:
                dest_path.unlink()
                raise IOError("Copy verification failed: file sizes don't match")
            
            return True
        except Exception as e:
            raise IOError(f"Failed to copy SLOB file: {e}")

    def import_dictionary(
        self,
        source_path: str,
        source_format: Optional[str] = None,
        output_name: Optional[str] = None
    ) -> Optional[str]:
        """
        Import a dictionary file/directory, converting to SLOB if needed.
        
        Supports any format recognized by PyGlossary.
        Transparently converts to SLOB or copies existing SLOB files.
        
        Args:
            source_path: Path to dictionary file or directory
            source_format: Optional PyGlossary format name (e.g., 'StarDict', 'MDict').
                          If not provided, will attempt auto-detection.
            output_name: Optional custom output filename (without extension).
                        If not provided, uses the source name.
                        
        Returns:
            Dictionary filename (*.slob) if successful, None on error
            
        Raises:
            FileNotFoundError: If source doesn't exist
            ValueError: If source is invalid
            PermissionError: If source is not accessible
            RuntimeError: If conversion fails
        """
        try:
            source = self._validate_input_source(source_path)
            
            # Determine output filename
            if output_name:
                slob_filename = output_name + '.slob'
            else:
                slob_filename = source.stem + '.slob'
            
            slob_dest = self.dicts_dir / slob_filename
            
            # Log format info
            format_info = f" (format: {source_format})" if source_format else ""
            print(f"Importing dictionary: {source.name}{format_info}")
            
            # Check if file already exists
            if slob_dest.exists():
                print(f"Dictionary already imported: {slob_filename}")
                # Ensure metadata exists
                if slob_filename not in self.metadata:
                    try:
                        metadata = self._extract_metadata(str(slob_dest), output_name or source.stem)
                        if metadata:
                            self.metadata[slob_filename] = metadata
                            self.metadata[slob_filename]['enabled'] = True
                            self._save_metadata()
                    except Exception as e:
                        print(f"Warning: Could not extract metadata: {e}")
                        # Still return filename even if metadata extraction fails
                
                return slob_filename
            
            # Detect if source is already SLOB
            is_slob_source = False
            if source.is_file() and source.suffix.lower() == '.slob':
                is_slob_source = True
            
            # Convert or copy to SLOB
            if is_slob_source:
                print(f"Copying SLOB file: {source.name}")
                self._copy_slob_file(source, slob_dest)
            else:
                print(f"Converting to SLOB{' using format: ' + source_format if source_format else ''}...")
                self._convert_to_slob(source, slob_dest, source_format)
            
            # Extract metadata from the SLOB file
            try:
                metadata = self._extract_metadata(str(slob_dest), output_name or source.stem)
                self.metadata[slob_filename] = metadata
                self.metadata[slob_filename]['enabled'] = True
                self._save_metadata()
                print(f"✓ Successfully imported: {slob_filename}")
            except Exception as e:
                # If metadata extraction fails, still return the filename
                # but log the error for the UI to handle
                print(f"✗ Metadata extraction failed: {e}")
                raise  # Re-raise so UI knows metadata couldn't be extracted
            
            return slob_filename
            
        except FileNotFoundError as e:
            print(f"FileNotFoundError: {e}")
            raise
        except ValueError as e:
            print(f"ValueError: {e}")
            raise
        except PermissionError as e:
            print(f"PermissionError: {e}")
            raise
        except RuntimeError as e:
            print(f"RuntimeError: {e}")
            raise
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Unexpected error importing dictionary: {e}")
            raise

    def _extract_metadata(self, dict_path: str, stem: str) -> Dict[str, Any]:
        """
        Extract metadata from a slob file.
        
        Args:
            dict_path: Path to the .slob file
            stem: Filename stem for fallback label
            
        Returns:
            Dictionary containing metadata
            
        Raises:
            Exception: If metadata extraction fails
        """
        from .slob import open as slob_open
        from ..utils import slob_tags
        
        with slob_open(dict_path) as dictionary:
            metadata = {
                'id': dictionary.id,
                'blob_count': dictionary.blob_count
            }
            metadata.update(dictionary.tags)
            
            if slob_tags.TAG_LABEL not in metadata:
                metadata[slob_tags.TAG_LABEL] = stem
            
            return metadata

    def delete_dictionary(self, filename: str) -> bool:
        """
        Delete a dictionary.
        
        Args:
            filename: Name of the dictionary file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            dict_path = self.dicts_dir / filename
            if dict_path.exists():
                dict_path.unlink()
            
            if filename in self.metadata:
                del self.metadata[filename]
                self._save_metadata()
            
            print(f"Deleted dictionary: {filename}")
            return True
        except Exception as e:
            print(f"Error deleting dictionary: {e}")
            return False

    def set_dictionary_enabled(self, filename: str, enabled: bool) -> bool:
        """
        Enable or disable a dictionary.
        
        Args:
            filename: Name of the dictionary file
            enabled: True to enable, False to disable
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if filename in self.metadata:
                self.metadata[filename]['enabled'] = enabled
                self._save_metadata()
                status = "enabled" if enabled else "disabled"
                print(f"Dictionary {status}: {filename}")
                return True
            return False
        except Exception as e:
            print(f"Error updating dictionary status: {e}")
            return False

    def get_dictionaries(self) -> List[Dict[str, Any]]:
        """
        Get list of all dictionaries with their metadata.
        
        Returns:
            List of dictionaries with metadata
        """
        dictionaries = []
        for filename, meta in self.metadata.items():
            dict_path = self.dicts_dir / filename
            if dict_path.exists():
                meta['filename'] = filename
                meta['path'] = str(dict_path)
                dictionaries.append(meta)
        
        return dictionaries

    def get_dictionary_info(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific dictionary.
        
        Args:
            filename: Name of the dictionary file
            
        Returns:
            Dictionary metadata or None
        """
        return self.metadata.get(filename)

    def get_supported_formats(self) -> Dict[str, str]:
        """
        Get list of supported input formats for conversion.
        
        Reads from pyglossary_input_fmts.json in the same directory.
        
        Returns:
            Dictionary mapping format keys to format names
        """
        if not self._pyglossary_available:
            return {}

        try:
            from pyglossary.glossary_v2 import Glossary

            result = {}
            for name in Glossary.readFormats:
                extensions = Glossary.plugins[name].extensions
                description = Glossary.plugins[name].description
                if not description:
                    description = name
                if '(' not in description and len(extensions) > 0:
                    value = description + "(" + ', '.join(extensions) + ")"
                else:
                    value = description
                result[name] = value

            return result
        except FileNotFoundError:
            print("Warning: pyglossary_input_fmts.json not found")
            return {}
        except json.JSONDecodeError:
            print("Warning: Invalid JSON in pyglossary_input_fmts.json")
            return {}
        except Exception as e:
            print(f"Warning: Could not load formats: {e}")
            return {}
