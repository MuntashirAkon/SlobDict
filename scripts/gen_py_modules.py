#!/usr/bin/env python3
"""
Generate python3-modules.json for Flatpak with correct lxml build command.

Extracts GNOME SDK version from Flatpak manifest, loads dependencies from
requirements.txt, runs flatpak-pip-generator, and patches the lxml module
to use --target for correct site-packages location.
"""

import json
import subprocess
import sys
import re
from pathlib import Path
from typing import Optional, List


def extract_sdk_version(yaml_file: str) -> Optional[str]:
    """
    Extract GNOME SDK version from Flatpak YAML manifest.
    
    Args:
        yaml_file: Path to Flatpak manifest (e.g., dev.muntashir.SlobDictGTK.yaml)
        
    Returns:
        SDK version (e.g., '47') or None if not found
    """
    try:
        with open(yaml_file, 'r') as f:
            content = f.read()
        
        # Match "runtime-version: '47'" or similar
        match = re.search(r"runtime-version:\s*['\"]?(\d+)['\"]?", content)
        if match:
            return match.group(1)
        
        print(f"Error: Could not find 'runtime-version' in {yaml_file}")
        return None
    
    except FileNotFoundError:
        print(f"Error: File not found: {yaml_file}")
        return None
    except Exception as e:
        print(f"Error reading YAML file: {e}")
        return None


def load_dependencies_from_requirements(requirements_file: str = "requirements.txt") -> List[str]:
    """
    Load dependencies from requirements.txt file.
    
    Args:
        requirements_file: Path to requirements.txt
        
    Returns:
        List of package names (without versions)
    """
    try:
        with open(requirements_file, 'r') as f:
            lines = f.readlines()
        
        dependencies = []
        for line in lines:
            # Strip whitespace
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Extract package name (before any version specifier)
            # Handles: "package", "package==1.0", "package>=1.0", "package[extra]", etc.
            package = re.split(r'[><=!\[]', line)[0].strip()
            if package:
                dependencies.append(package)
        
        if not dependencies:
            print(f"Warning: No dependencies found in {requirements_file}")
            return []
        
        print(f"✓ Loaded {len(dependencies)} dependencies from {requirements_file}")
        print(f"  Dependencies: {', '.join(dependencies)}")
        return dependencies
    
    except FileNotFoundError:
        print(f"Error: File not found: {requirements_file}")
        return []
    except Exception as e:
        print(f"Error reading requirements file: {e}")
        return []


def generate_python_modules(sdk_version: str, dependencies: List[str], output_file: str = "python3-modules.json") -> bool:
    """
    Run flatpak-pip-generator to create python3-modules.json.
    
    Args:
        sdk_version: GNOME SDK version (e.g., '47')
        dependencies: List of package names to install
        output_file: Output filename for generated JSON
        
    Returns:
        True if successful, False otherwise
    """
    cmd = [
        "python3",
        "flatpak-pip-generator.py",
        f"--runtime=org.gnome.Sdk//{sdk_version}",
        "--output", output_file,
    ] + dependencies
    
    print(f"\nRunning: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✓ Generated {output_file}")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running flatpak-pip-generator.py: {e}")
        print(f"stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print("Error: flatpak-pip-generator.py not found. Install with:")
        print("  pip install flatpak-pip-generator")
        print("  wget https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/master/pip/flatpak-pip-generator.py")
        return False

def patch_lxml_build_command(json_file: str) -> bool:
    """
    Modify lxml module in JSON to use --target instead of --prefix.
    
    Args:
        json_file: Path to python3-modules.json
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        # Find and patch lxml module
        patched = False
        for module in data.get('modules', []):
            if module.get('name') == 'python3-lxml':
                # Get current build-commands
                build_commands = module.get('build-commands', [])
                
                # Patch the pip install command
                new_commands = []
                for cmd in build_commands:
                    if 'pip3 install' in cmd and 'lxml' in cmd:
                        # Replace --prefix=${FLATPAK_DEST} with --target
                        cmd = cmd.replace(
                            '--prefix=${FLATPAK_DEST}',
                            '--target=${FLATPAK_DEST}/lib/python3.13/site-packages'
                        )
                        print(f"Patched lxml build-command:")
                        print(f"  {cmd}")
                    new_commands.append(cmd)
                
                module['build-commands'] = new_commands
                patched = True
                break
        
        if not patched:
            print("Warning: Could not find 'python3-lxml' module in JSON")
            print("Available modules:")
            for module in data.get('modules', []):
                print(f"  - {module.get('name')}")
            return False
        
        # Write back modified JSON
        with open(json_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Patched {json_file}")
        return True
    
    except FileNotFoundError:
        print(f"Error: File not found: {json_file}")
        return False
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return False
    except Exception as e:
        print(f"Error patching JSON: {e}")
        return False

def patch_pygments_build_command(json_file: str) -> bool:
    """
    Modify pygments module in JSON to use --target instead of --prefix.
    
    Args:
        json_file: Path to python3-modules.json
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        # Find and patch pygments module
        patched = False
        for module in data.get('modules', []):
            if module.get('name') == 'python3-pygments':
                # Get current build-commands
                build_commands = module.get('build-commands', [])
                
                # Patch the pip install command
                new_commands = []
                for cmd in build_commands:
                    if 'pip3 install' in cmd and 'pygments' in cmd:
                        # Replace --prefix=${FLATPAK_DEST} with --target
                        cmd = cmd.replace(
                            '--prefix=${FLATPAK_DEST}',
                            '--target=${FLATPAK_DEST}/lib/python3.13/site-packages'
                        )
                        print(f"Patched pygments build-command:")
                        print(f"  {cmd}")
                    new_commands.append(cmd)
                
                module['build-commands'] = new_commands
                patched = True
                break
        
        if not patched:
            print("Warning: Could not find 'python3-pygments' module in JSON")
            print("Available modules:")
            for module in data.get('modules', []):
                print(f"  - {module.get('name')}")
            return False
        
        # Write back modified JSON
        with open(json_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Patched {json_file}")
        return True
    
    except FileNotFoundError:
        print(f"Error: File not found: {json_file}")
        return False
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return False
    except Exception as e:
        print(f"Error patching JSON: {e}")
        return False

def main():
    """Main entry point."""
    # Default files
    manifest_file = "dev.muntashir.SlobDictGTK.yaml"
    requirements_file = "requirements.txt"
    output_json = "python3-modules.json"
    
    # Allow custom manifest via CLI argument
    if len(sys.argv) > 1:
        manifest_file = sys.argv[1]
    if len(sys.argv) > 2:
        requirements_file = sys.argv[2]
    
    print(f"Reading Flatpak manifest: {manifest_file}")
    print(f"Reading dependencies from: {requirements_file}\n")
    
    # Step 1: Extract SDK version
    sdk_version = extract_sdk_version(manifest_file)
    if not sdk_version:
        print("Failed to extract SDK version. Exiting.")
        return 1
    
    print(f"✓ Found GNOME SDK version: {sdk_version}\n")
    
    # Step 2: Load dependencies from requirements.txt
    dependencies = load_dependencies_from_requirements(requirements_file)
    if not dependencies:
        print("Failed to load dependencies. Exiting.")
        return 1
    
    # Step 3: Generate python3-modules.json
    if not generate_python_modules(sdk_version, dependencies, output_json):
        print("Failed to generate python3-modules.json. Exiting.")
        return 1
    
    # Step 4: Patch lxml build command
    print("\nPatching generated JSON...")
    if not patch_lxml_build_command(output_json):
        print("Warning: Could not patch lxml build command (non-fatal)")
        # Don't exit on this - it's a "nice to have" patch
    
    # Step 5: Patch pygments build command
    print("\nPatching generated JSON...")
    if not patch_pygments_build_command(output_json):
        print("Warning: Could not patch pygments build command (non-fatal)")
        # Don't exit on this - it's a "nice to have" patch
    
    print(f"\n✓ Done! Generated and patched {output_json}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
