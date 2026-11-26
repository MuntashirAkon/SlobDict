# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import hashlib
import shutil
import base64
import tempfile
import re
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict, Any
from enum import Enum
from urllib.parse import urljoin, urlparse
import plistlib
import logging


logger = logging.getLogger(__name__)


class DictionaryCategory(Enum):
    """Semantic category shown to users."""
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
    type: str  # PyGlossary input format, or "slob" for a native SLOB file
    version: int
    size: int
    hash: str
    hash_algo: str
    url: str
    copyright: Optional[str] = None
    compression: Optional[str] = None
    path: Optional[str] = None
    category: Optional[str] = None
    
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
            compression=data.get('compression'),
            path=data.get('path'),
            category=data.get('category')
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
        return sorted(set(d.lang for d in self.dictionaries if d.lang))


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
        
        dictionaries_by_id: Dict[str, Dictionary] = {}
        base_url = None
        
        assets = data.get('Assets', [])
        if not isinstance(assets, list):
            raise ValueError("Invalid Apple catalog: Assets must be a list")
        for asset in assets:
            if not isinstance(asset, dict):
                raise ValueError("Invalid Apple catalog: each asset must be an object")
            # Construct full URL from base URL and relative path
            if '__BaseURL' in asset:
                base_url = asset['__BaseURL']
                relative_path = asset.get('__RelativePath', '')
                url = urljoin(base_url, relative_path)
            else:
                url = asset.get('url', '')
            
            # Convert hash measurement (base64) if needed
            hash_value = asset.get('_Measurement', '')
            if isinstance(hash_value, bytes):
                hash_value = base64.b64encode(hash_value).decode('ascii')
            hash_algo = asset.get('_MeasurementAlgorithm', 'SHA-256')
            
            dictionary = Dictionary(
                id=asset.get('DictionaryIdentifier', ''),
                name=asset.get('DictionaryPackageDisplayName', ''),
                lang=asset.get('Language', ''),
                type='AppleDictBin',
                version=asset.get('_ContentVersion', 1),
                size=asset.get('_DownloadSize', 0),
                hash=hash_value,
                hash_algo=hash_algo,
                url=url,
                copyright=asset.get('DictionaryCopyright'),
                compression=asset.get('_CompressionAlgorithm'),
                category=asset.get('DictionaryType', DictionaryCategory.MONOLINGUAL.value)
            )
            current = dictionaries_by_id.get(dictionary.id)
            if current is None or dictionary.version >= current.version:
                # Catalogs may retain older assets for the same dictionary ID.
                # Keep a single entry and prefer the newest version.
                dictionaries_by_id[dictionary.id] = dictionary

        dictionaries = list(dictionaries_by_id.values())
        
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
        source_lower = source_path.lower().split('?', 1)[0]
        
        # Try PLIST/XML first (for .plist or .xml files)
        if source_lower.endswith(('.plist', '.xml')):
            try:
                data: Dict[str, Any] = plistlib.loads(content)
                logger.debug(f"Parsed {source_path} as PLIST/XML")
            except Exception as e:
                logger.warning(f"Failed to parse {source_path} as PLIST: {e}")
            else:
                if not isinstance(data, dict):
                    raise ValueError("Catalog root must be an object")
                if data.get('AssetType') == 'com.apple.MobileAsset.DictionaryServices.dictionaryOSX':
                    return CatalogParser._normalize_apple_catalog(data)
                return data
        
        # Try JSON
        try:
            data = json.loads(content.decode('utf-8'))
            if not isinstance(data, dict):
                raise ValueError("Catalog root must be an object")
            logger.debug(f"Parsed {source_path} as JSON")
            
            # Check if it's an Apple catalog in JSON format
            if data.get('AssetType') == 'com.apple.MobileAsset.DictionaryServices.dictionaryOSX':
                return CatalogParser._normalize_apple_catalog(data)
            else:
                # Assume it's already in our format
                return data
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
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
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the catalog manager.
        
        Args:
            cache_dir: Directory to store cached catalogs. If omitted, uses the
                       application's cache directory.
        """
        if cache_dir is None:
            from ..utils.utils import get_config_dir
            app_data_dir = get_config_dir()
            cache_dir = str(app_data_dir / "cache" / "catalogs")
        else:
            from ..utils.utils import get_config_dir
            app_data_dir = get_config_dir()
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory catalogs
        self.catalogs: Dict[str, DictionaryCatalog] = {}
        self._sources_file = app_data_dir / "catalog_sources.json"
        self.catalog_sources = self._load_catalog_sources()
        
        logger.info(f"DictionaryCatalogManager initialized with cache dir: {self.cache_dir}")

    def _load_catalog_sources(self) -> List[str]:
        """Load the configured catalog source list."""
        try:
            with self._sources_file.open('r', encoding='utf-8') as source_file:
                sources = json.load(source_file)
            if isinstance(sources, list) and all(isinstance(source, str) for source in sources):
                return list(dict.fromkeys(sources))
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load catalog source list: {e}")
        return []

    def _save_catalog_sources(self) -> None:
        """Persist configured catalog sources."""
        self._sources_file.parent.mkdir(parents=True, exist_ok=True)
        with self._sources_file.open('w', encoding='utf-8') as source_file:
            json.dump(self.catalog_sources, source_file, indent=2)

    def add_catalog(self, source: str, force_refresh: bool = False) -> DictionaryCatalog:
        """Load and register a catalog source."""
        catalog = self.load_catalog(source, force_refresh=force_refresh)
        if source not in self.catalog_sources:
            self.catalog_sources.append(source)
            self._save_catalog_sources()
        return catalog

    def remove_catalog(self, source: str) -> bool:
        """Forget a catalog and its cache without deleting installed dictionaries."""
        existed = source in self.catalog_sources or source in self.catalogs
        self.catalog_sources = [configured for configured in self.catalog_sources if configured != source]
        self.catalogs.pop(source, None)
        self.clear_cache(source)
        if existed:
            self._save_catalog_sources()
        return existed

    def load_configured_catalogs(self, force_refresh: bool = False) -> List[DictionaryCatalog]:
        """Load all configured catalogs, logging individual failures."""
        loaded = []
        for source in self.catalog_sources:
            try:
                loaded.append(self.load_catalog(source, force_refresh=force_refresh))
            except Exception:
                logger.exception(f"Failed to load catalog: {source}")
        return loaded
    
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
    
    def _load_remote_catalog(self, url: str, etag: Optional[str] = None) -> tuple[Optional[bytes], Optional[str]]:
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
            request = urllib.request.Request(url)
            if etag:
                request.add_header('If-None-Match', etag)
            try:
                response = urllib.request.urlopen(request, timeout=30)
            except urllib.error.HTTPError as e:
                if e.code == 304:
                    return None, etag
                raise
            with response:
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
        
        # Apple parsing produces Dictionary objects. Persist a JSON-safe
        # normalized form so cached catalogs can be reconstructed on reload.
        serializable_data = dict(data)
        serializable_data['dictionaries'] = [
            dictionary.to_dict() if isinstance(dictionary, Dictionary) else dictionary
            for dictionary in data.get('dictionaries', [])
        ]
        self._atomic_write_json(cache_path, serializable_data)
        
        # Save metadata
        metadata = {
            'source': source,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'etag': etag
        }
        self._atomic_write_json(meta_path, metadata)
        
        logger.debug(f"Cached catalog from {source}")

    @staticmethod
    def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
        """Write JSON through a temporary file to prevent readers seeing partial data."""
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=path.parent,
                prefix=f".{path.name}.", suffix='.tmp', delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(data, temporary_file, indent=2)
                temporary_file.flush()
            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    
    def _load_cache(self, source: str) -> Optional[Dict[str, Any]]:
        """Load catalog from cache if it exists."""
        cache_path = self._get_cache_path(source)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r') as f:
                data: Dict[str, Any] = json.load(f)
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
        
        cached_data = None
        cached_catalog = None
        if is_remote:
            # Try to load from cache first
            cached_data = self._load_cache(source)
            if cached_data:
                try:
                    cached_catalog = self._create_catalog_from_data(
                        source, cached_data, cached_data.get('type', 'slobdict')
                    )
                except (TypeError, ValueError) as e:
                    logger.warning(f"Ignoring incompatible catalog cache for {source}: {e}")
                    cached_data = None
                    cached_catalog = None
                if cached_catalog is not None and not force_refresh:
                    self.catalogs[source] = cached_catalog
                    return cached_catalog
        
        # Load from source
        if is_remote:
            content, etag = self._load_remote_catalog(
                source, self._get_cached_etag(source) if force_refresh and cached_data is not None else None
            )
            if content is None and cached_catalog is not None:
                self.catalogs[source] = cached_catalog
                return cached_catalog
        else:
            content = self._load_local_catalog(source)
        
        # Parse catalog
        parsed_data = CatalogParser.parse(content, source)

        # Validate before caching so malformed catalogs never poison the cache.
        catalog = self._create_catalog_from_data(source, parsed_data, parsed_data.get('type', 'slobdict'))
        if is_remote:
            self._save_cache(source, parsed_data, etag)
        self.catalogs[source] = catalog
        
        return catalog
    
    def _create_catalog_from_data(self, source: str, data: Dict[str, Any], cat_type: str) -> DictionaryCatalog:
        """Create DictionaryCatalog object from parsed data."""
        if not isinstance(data, dict):
            raise ValueError("Catalog root must be an object")
        raw_dictionaries = data.get('dictionaries')
        if not isinstance(raw_dictionaries, list):
            raise ValueError("Catalog must contain a dictionaries list")
        catalog_version = data.get('version', 1)
        if isinstance(catalog_version, bool) or not isinstance(catalog_version, int) or catalog_version < 0:
            raise ValueError("Catalog version must be a non-negative integer")
        dictionaries_by_id: Dict[str, Dictionary] = {}
        
        for index, dict_data in enumerate(raw_dictionaries):
            if isinstance(dict_data, Dictionary):
                dictionary = dict_data
            else:
                if not isinstance(dict_data, dict):
                    raise ValueError(f"Invalid dictionary entry at index {index}: expected an object")
                dictionary = Dictionary.from_dict(dict_data)
            self._validate_dictionary(dictionary, index)
            current = dictionaries_by_id.get(dictionary.id)
            if current is None or dictionary.version >= current.version:
                dictionaries_by_id[dictionary.id] = dictionary

        dictionaries = list(dictionaries_by_id.values())
        
        catalog = DictionaryCatalog(
            source=source,
            type=cat_type,
            version=catalog_version,
            dictionaries=dictionaries,
            last_updated=datetime.now(timezone.utc)
        )
        
        return catalog

    @staticmethod
    def _validate_dictionary(dictionary: Dictionary, index: int) -> None:
        """Validate catalog metadata before it reaches download/import code."""
        def invalid(field: str, requirement: str) -> ValueError:
            return ValueError(f"Invalid dictionary entry at index {index}: {field} {requirement}")

        for field_name in ("id", "name", "url"):
            value = getattr(dictionary, field_name)
            if not isinstance(value, str) or not value.strip():
                raise invalid(field_name, "is required")

        if not isinstance(dictionary.lang, str):
            raise invalid("lang", "must be a string")
        if dictionary.type is None:
            dictionary.type = ""
        elif not isinstance(dictionary.type, str):
            raise invalid("type", "must be a string when provided")
        if dictionary.category is not None and not isinstance(dictionary.category, str):
            raise invalid("category", "must be a string when provided")
        categories = {category.value for category in DictionaryCategory}
        if dictionary.category is not None and dictionary.category not in categories:
            raise invalid("category", f"must be one of {', '.join(sorted(categories))}")
        if dictionary.copyright is not None and not isinstance(dictionary.copyright, str):
            raise invalid("copyright", "must be a string when provided")
        if isinstance(dictionary.size, bool) or not isinstance(dictionary.size, int) or dictionary.size < 0:
            raise invalid("size", "must be a non-negative integer")
        if isinstance(dictionary.version, bool) or not isinstance(dictionary.version, int) or dictionary.version < 0:
            raise invalid("version", "must be a non-negative integer")

        algorithm_aliases = {
            "SHA1": "SHA-1", "SHA-1": "SHA-1",
            "SHA256": "SHA-256", "SHA-256": "SHA-256",
            "SHA512": "SHA-512", "SHA-512": "SHA-512",
        }
        if not isinstance(dictionary.hash_algo, str):
            raise invalid("hash_algo", "must be one of SHA-1, SHA-256, or SHA-512")
        algorithm_key = dictionary.hash_algo.strip().upper().replace("_", "-")
        canonical_algorithm = algorithm_aliases.get(algorithm_key)
        if canonical_algorithm is None:
            raise invalid("hash_algo", "must be one of SHA-1, SHA-256, or SHA-512")
        dictionary.hash_algo = canonical_algorithm

        if not isinstance(dictionary.hash, str) or not dictionary.hash.strip():
            raise invalid("hash", "is required")
        dictionary.hash = dictionary.hash.strip()
        hash_size = hashlib.new(canonical_algorithm.lower().replace("-", "")).digest_size
        if re.fullmatch(r"[A-Fa-f0-9]+", dictionary.hash) and len(dictionary.hash) == hash_size * 2:
            encoded_hash = bytes.fromhex(dictionary.hash)
        else:
            try:
                encoded_hash = base64.b64decode(
                    dictionary.hash + "=" * (-len(dictionary.hash) % 4), validate=True
                )
            except (ValueError, TypeError) as e:
                raise invalid("hash", "must be valid hexadecimal or base64") from e
        if len(encoded_hash) != hash_size:
            raise invalid("hash", f"must encode a {canonical_algorithm} digest")

        parsed_url = urlparse(dictionary.url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise invalid("url", "must be an HTTP or HTTPS URL")

        if dictionary.compression is not None:
            if not isinstance(dictionary.compression, str):
                raise invalid("compression", "must be 'zip' when provided")
            compression = dictionary.compression.strip().casefold()
            if compression not in ("", "zip"):
                raise invalid("compression", "supports only 'zip'")
            dictionary.compression = compression or None

        if dictionary.path is not None:
            if not isinstance(dictionary.path, str):
                raise invalid("path", "must be a relative path when provided")
            normalized_path = dictionary.path.replace("\\", "/")
            path = PurePosixPath(normalized_path)
            if not normalized_path.strip():
                dictionary.path = None
            elif (path.is_absolute() or path.as_posix() == "." or
                    any(part in ("..", "") for part in path.parts) or
                    (len(normalized_path) >= 2 and normalized_path[1] == ":")):
                raise invalid("path", "must be a safe relative path")
            else:
                dictionary.path = path.as_posix()
    
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
            self.catalogs.pop(source, None)
            
            logger.info(f"Cleared cache for: {source}")
        else:
            shutil.rmtree(self.cache_dir, ignore_errors=True)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.catalogs.clear()
            
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
        """Find all dictionaries using a specific PyGlossary input format."""
        result = []
        for source, catalog in self.catalogs.items():
            for dictionary in catalog.dictionaries:
                if dictionary.type == dict_type:
                    result.append((source, dictionary))
        return result

    def find_dictionaries_by_category(self, category: str) -> List[tuple[str, Dictionary]]:
        """Find all dictionaries in a user-facing semantic category."""
        result = []
        for source, catalog in self.catalogs.items():
            for dictionary in catalog.dictionaries:
                if dictionary.category == category:
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
