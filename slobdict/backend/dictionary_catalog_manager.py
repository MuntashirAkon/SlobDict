# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import os
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any
from enum import Enum
from urllib.parse import urljoin
import plistlib
import logging


logger = logging.getLogger(__name__)


class DictionaryType(Enum):
    """Dictionary type enumeration."""
    MONOLINGUAL = "Monolingual"
    BILINGUAL = "Bilingual"
    THESAURUS = "Thesaurus"


class HashAlgorithm(Enum):
    """Supported hash algorithms."""
    SHA1 = "SHA-1"
    SHA256 = "SHA-256"
    SHA512 = "SHA-512"


@dataclass
class Dictionary:
    """Represents a single dictionary in a catalog."""
    
    id: str
    name: str
    lang: str
    type: str
    version: int
    size: int
    hash: str
    hash_algo: str
    url: str
    copyright: Optional[str] = None
    compression: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Dictionary':
        """Create from dictionary representation."""
        return Dictionary(
            id=data.get('id', ''),
            name=data.get('name', ''),
            lang=data.get('lang', ''),
            type=data.get('type', ''),
            version=data.get('version', 0),
            size=data.get('size', 0),
            hash=data.get('hash', ''),
            hash_algo=data.get('hash_algo', 'SHA-256'),
            url=data.get('url', ''),
            copyright=data.get('copyright'),
            compression=data.get('compression')
        )


@dataclass
class DictionaryCatalog:
    """Represents a catalog containing dictionaries."""
    
    source: str  # File path or URL
    type: str  # "apple" or "slobdict"
    version: int
    dictionaries: List[Dictionary] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    etag: Optional[str] = None  # For HTTP caching
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'type': 'slobdict',
            'version': self.version,
            'dictionaries': [d.to_dict() for d in self.dictionaries]
        }
    
    def get_dictionary(self, dict_id: str) -> Optional[Dictionary]:
        """Get dictionary by ID."""
        for d in self.dictionaries:
            if d.id == dict_id:
                return d
        return None
    
    def get_dictionaries_by_language(self, lang: str) -> List[Dictionary]:
        """Get all dictionaries for a specific language."""
        return [d for d in self.dictionaries if d.lang == lang]
    
    def get_all_languages(self) -> List[str]:
        """Get list of all languages in catalog."""
        return sorted(set(d.lang for d in self.dictionaries))


class CatalogParser:
    """Handles parsing of different catalog formats."""
    
    @staticmethod
    def _normalize_apple_catalog(data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Apple catalog format to our standard format."""
        if data.get('AssetType') != 'com.apple.MobileAsset.DictionaryServices.dictionaryOSX':
            raise ValueError(
                f"Invalid Apple catalog type: {data.get('AssetType')}. "
                "Expected: com.apple.MobileAsset.DictionaryServices.dictionaryOSX"
            )
        
        dictionaries = []
        base_url = None
        
        for asset in data.get('Assets', []):
            # Construct full URL from base URL and relative path
            if '__BaseURL' in asset:
                base_url = asset['__BaseURL']
                relative_path = asset.get('__RelativePath', '')
                url = urljoin(base_url, relative_path)
            else:
                url = asset.get('url', '')
            
            # Convert hash measurement (base64) if needed
            hash_value = asset.get('_Measurement', '')
            hash_algo = asset.get('_MeasurementAlgorithm', 'SHA-256')
            
            dictionary = Dictionary(
                id=asset.get('DictionaryIdentifier', ''),
                name=asset.get('DictionaryPackageDisplayName', ''),
                lang=asset.get('Language', ''),
                type=asset.get('DictionaryType', 'Monolingual'),
                version=asset.get('_ContentVersion', 1),
                size=asset.get('_DownloadSize', 0),
                hash=hash_value,
                hash_algo=hash_algo,
                url=url,
                copyright=asset.get('DictionaryCopyright'),
                compression=asset.get('_CompressionAlgorithm')
            )
            dictionaries.append(dictionary)
        
        return {
            'type': 'apple',
            'version': int(data.get('FormatVersion', 1)),
            'dictionaries': dictionaries
        }
    
    @staticmethod
    def parse(content: bytes, source_path: str) -> Dict[str, Any]:
        """
        Parse catalog from bytes (file or HTTP response).
        
        Auto-detects format (PLIST/XML or JSON).
        Converts Apple format to standard format if needed.
        """
        source_lower = source_path.lower()
        
        # Try PLIST/XML first (for .plist or .xml files)
        if source_lower.endswith(('.plist', '.xml')):
            try:
                data = plistlib.loads(content)
                logger.debug(f"Parsed {source_path} as PLIST/XML")
                
                # Check if it's an Apple catalog
                if data.get('AssetType') == 'com.apple.MobileAsset.DictionaryServices.dictionaryOSX':
                    return CatalogParser._normalize_apple_catalog(data)
                else:
                    # Assume it's already in our format
                    return data
            except Exception as e:
                logger.warning(f"Failed to parse {source_path} as PLIST: {e}")
        
        # Try JSON
        try:
            data = json.loads(content.decode('utf-8'))
            logger.debug(f"Parsed {source_path} as JSON")
            
            # Check if it's an Apple catalog in JSON format
            if data.get('AssetType') == 'com.apple.MobileAsset.DictionaryServices.dictionaryOSX':
                return CatalogParser._normalize_apple_catalog(data)
            else:
                # Assume it's already in our format
                return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse {source_path} as JSON: {e}")
            raise ValueError(f"Could not parse catalog from {source_path}. Unsupported format.")


class DictionaryCatalogManager:
    """
    Manages dictionary catalogs from various sources.
    
    Features:
    - Load catalogs from files or URLs
    - Auto-detect format (PLIST, XML, JSON)
    - Convert Apple catalog format to standard format
    - Cache management with HTTP ETag support
    - Query and filter dictionaries across catalogs
    """
    
    def __init__(self, cache_dir: str = None):
        """
        Initialize the catalog manager.
        
        Args:
            cache_dir: Directory to store cached catalogs.
                      If None, uses ~/.cache/dict-app/catalogs/
        """
        if cache_dir is None:
            cache_dir = os.path.expanduser('~/.cache/dict-app/catalogs/')
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory catalogs
        self.catalogs: Dict[str, DictionaryCatalog] = {}
        
        logger.info(f"DictionaryCatalogManager initialized with cache dir: {self.cache_dir}")
    
    def _get_cache_path(self, source: str) -> Path:
        """
        Generate cache file path for a source.
        
        Uses MD5 hash of source URL/path as filename.
        """
        source_hash = hashlib.md5(source.encode()).hexdigest()
        return self.cache_dir / f"{source_hash}.json"
    
    def _get_cache_metadata_path(self, source: str) -> Path:
        """Get path to cache metadata file (stores ETag, timestamps, etc)."""
        source_hash = hashlib.md5(source.encode()).hexdigest()
        return self.cache_dir / f"{source_hash}.meta.json"
    
    def _load_local_catalog(self, file_path: str) -> bytes:
        """Load catalog from local file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Catalog file not found: {file_path}")
        
        logger.info(f"Loading catalog from file: {file_path}")
        return path.read_bytes()
    
    def _load_remote_catalog(self, url: str) -> tuple[bytes, Optional[str]]:
        """
        Load catalog from remote URL.
        
        Returns:
            Tuple of (content, etag)
        """
        try:
            import urllib.request
            import urllib.error
        except ImportError:
            raise ImportError("urllib is required for remote catalog loading")
        
        logger.info(f"Downloading catalog from: {url}")
        
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read()
                etag = response.headers.get('ETag')
                
                logger.debug(f"Downloaded {len(content)} bytes from {url}")
                return content, etag
        except urllib.error.URLError as e:
            raise IOError(f"Failed to download catalog from {url}: {e}")
    
    def _save_cache(self, source: str, data: Dict[str, Any], etag: Optional[str] = None) -> None:
        """Save parsed catalog to cache."""
        cache_path = self._get_cache_path(source)
        meta_path = self._get_cache_metadata_path(source)
        
        # Save catalog data
        with open(cache_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        # Save metadata
        metadata = {
            'source': source,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'etag': etag
        }
        with open(meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.debug(f"Cached catalog from {source}")
    
    def _load_cache(self, source: str) -> Optional[Dict[str, Any]]:
        """Load catalog from cache if it exists."""
        cache_path = self._get_cache_path(source)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r') as f:
                data = json.load(f)
            logger.debug(f"Loaded catalog from cache: {source}")
            return data
        except Exception as e:
            logger.warning(f"Failed to load cache for {source}: {e}")
            return None
    
    def _get_cached_etag(self, source: str) -> Optional[str]:
        """Get cached ETag for a source."""
        meta_path = self._get_cache_metadata_path(source)
        
        if not meta_path.exists():
            return None
        
        try:
            with open(meta_path, 'r') as f:
                metadata = json.load(f)
            return metadata.get('etag')
        except Exception:
            return None
    
    def _is_remote_source(self, source: str) -> bool:
        """Check if source is a remote URL."""
        return source.startswith(('http://', 'https://'))
    
    def load_catalog(self, source: str, force_refresh: bool = False) -> DictionaryCatalog:
        """
        Load a catalog from a file or remote URL.
        
        Args:
            source: File path or URL to catalog
            force_refresh: If True, ignore cache and re-download/re-parse
        
        Returns:
            DictionaryCatalog object
        
        Raises:
            FileNotFoundError: If local file doesn't exist
            IOError: If remote download fails
            ValueError: If catalog format is invalid
        """
        # Check if already loaded
        if source in self.catalogs and not force_refresh:
            logger.debug(f"Using cached catalog in memory: {source}")
            return self.catalogs[source]
        
        is_remote = self._is_remote_source(source)
        content = None
        etag = None
        
        if is_remote and not force_refresh:
            # Try to load from cache first
            cached_data = self._load_cache(source)
            if cached_data:
                catalog = self._create_catalog_from_data(source, cached_data, 'apple')
                self.catalogs[source] = catalog
                return catalog
        
        # Load from source
        if is_remote:
            content, etag = self._load_remote_catalog(source)
        else:
            content = self._load_local_catalog(source)
        
        # Parse catalog
        parsed_data = CatalogParser.parse(content, source)
        
        # Save to cache
        if is_remote:
            self._save_cache(source, parsed_data, etag)
        
        # Create catalog object
        catalog = self._create_catalog_from_data(source, parsed_data, parsed_data.get('type', 'slobdict'))
        self.catalogs[source] = catalog
        
        return catalog
    
    def _create_catalog_from_data(self, source: str, data: Dict[str, Any], cat_type: str) -> DictionaryCatalog:
        """Create DictionaryCatalog object from parsed data."""
        dictionaries = []
        
        for dict_data in data.get('dictionaries', []):
            if isinstance(dict_data, Dictionary):
                dictionaries.append(dict_data)
            else:
                dictionaries.append(Dictionary.from_dict(dict_data))
        
        catalog = DictionaryCatalog(
            source=source,
            type=cat_type,
            version=data.get('version', 1),
            dictionaries=dictionaries,
            last_updated=datetime.now(timezone.utc)
        )
        
        return catalog
    
    def unload_catalog(self, source: str) -> bool:
        """
        Unload a catalog from memory.
        
        Returns:
            True if catalog was unloaded, False if not found
        """
        if source in self.catalogs:
            del self.catalogs[source]
            logger.info(f"Unloaded catalog: {source}")
            return True
        return False
    
    def clear_cache(self, source: Optional[str] = None) -> None:
        """
        Clear cache files.
        
        Args:
            source: If provided, only clear cache for this source.
                   If None, clear all cache.
        """
        if source:
            cache_path = self._get_cache_path(source)
            meta_path = self._get_cache_metadata_path(source)
            
            cache_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            
            logger.info(f"Cleared cache for: {source}")
        else:
            shutil.rmtree(self.cache_dir, ignore_errors=True)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info("Cleared all cache")
    
    def get_catalog(self, source: str) -> Optional[DictionaryCatalog]:
        """Get a loaded catalog by source."""
        return self.catalogs.get(source)
    
    def get_all_catalogs(self) -> List[DictionaryCatalog]:
        """Get all loaded catalogs."""
        return list(self.catalogs.values())
    
    def get_all_dictionaries(self) -> List[tuple[str, Dictionary]]:
        """
        Get all dictionaries from all catalogs.
        
        Returns:
            List of tuples (source, dictionary)
        """
        result = []
        for source, catalog in self.catalogs.items():
            for dictionary in catalog.dictionaries:
                result.append((source, dictionary))
        return result
    
    def find_dictionary(self, dict_id: str) -> Optional[tuple[str, Dictionary]]:
        """
        Find a dictionary by ID across all loaded catalogs.
        
        Returns:
            Tuple of (source, dictionary) or None if not found
        """
        for source, catalog in self.catalogs.items():
            for dictionary in catalog.dictionaries:
                if dictionary.id == dict_id:
                    return (source, dictionary)
        return None
    
    def find_dictionaries_by_language(self, lang: str) -> List[tuple[str, Dictionary]]:
        """
        Find all dictionaries for a language across all loaded catalogs.
        
        Returns:
            List of tuples (source, dictionary)
        """
        result = []
        for source, catalog in self.catalogs.items():
            for dictionary in catalog.get_dictionaries_by_language(lang):
                result.append((source, dictionary))
        return result
    
    def find_dictionaries_by_type(self, dict_type: str) -> List[tuple[str, Dictionary]]:
        """
        Find all dictionaries of a specific type.
        
        Args:
            dict_type: One of 'Monolingual', 'Bilingual', 'Thesaurus'
        
        Returns:
            List of tuples (source, dictionary)
        """
        result = []
        for source, catalog in self.catalogs.items():
            for dictionary in catalog.dictionaries:
                if dictionary.type == dict_type:
                    result.append((source, dictionary))
        return result
    
    def get_all_languages(self) -> List[str]:
        """Get list of all languages available across all catalogs."""
        languages = set()
        for catalog in self.catalogs.values():
            languages.update(catalog.get_all_languages())
        return sorted(list(languages))
    
    def get_catalog_statistics(self) -> Dict[str, Any]:
        """Get statistics about loaded catalogs."""
        total_dicts = sum(len(cat.dictionaries) for cat in self.catalogs.values())
        languages = self.get_all_languages()
        
        return {
            'total_catalogs': len(self.catalogs),
            'total_dictionaries': total_dicts,
            'languages': languages,
            'sources': list(self.catalogs.keys())
        }
    
    def export_catalog(self, source: str, output_path: str) -> None:
        """
        Export a loaded catalog to a JSON file.
        
        Args:
            source: Source of the catalog to export
            output_path: File path to save the exported catalog
        """
        catalog = self.get_catalog(source)
        if not catalog:
            raise ValueError(f"Catalog not found: {source}")
        
        data = catalog.to_dict()
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Exported catalog to: {output_path}")
