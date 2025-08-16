#!/usr/bin/env python3
"""
Roam Research Encrypted Graph Migration Tool
============================================
A comprehensive solution for migrating encrypted Roam Research graphs with all media files.

This tool solves the long-standing issue of broken media links when exporting encrypted
Roam Research graphs. It processes the exported backup, uploads all media files to 
Cloudflare R2 (or compatible S3 storage), and updates all references in the JSON backup.

Author: Rodrigo Pinto
License: MIT
Version: 1.0.0
"""

import os
import json
import requests
import hashlib
import re
from pathlib import Path
from datetime import datetime
import time
import argparse
from typing import Dict, List, Tuple, Optional
import sys

# DEFAULT CONFIGURATION
DEFAULT_CONFIG = {
    'API_TOKEN': '',  # Your Cloudflare API token with R2 permissions
    'ACCOUNT_ID': '',  # Your Cloudflare account ID
    'BUCKET_NAME': '',  # Your R2 bucket name
    'PUBLIC_URL': '',  # Public URL of your R2 bucket
    
    'FILES_FOLDER': '',  # Path to "Files and images" folder from Roam export
    'ROAM_JSON': '',  # Path to the exported Roam JSON file
    'OUTPUT_JSON': '',  # Path for the updated JSON file
    'PROGRESS_FILE': '',  # Path to save progress (for resume capability)
    
    'KEEP_ORIGINAL_NAMES': True,  # Keep original filenames for traceability
    'CLEAN_FILENAMES': True,  # Clean problematic characters from filenames
    'BATCH_SIZE': 50,  # Number of files to process before saving progress
    'MAX_RETRIES': 3,  # Maximum retries for failed uploads
}

class RoamMediaMigrator:
    """
    Main class for migrating Roam Research encrypted graph media files.
    Handles all edge cases including files with numbers, spaces, and special characters.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.validate_config()
        
        # API Configuration
        self.api_token = config['API_TOKEN']
        self.account_id = config['ACCOUNT_ID']
        self.bucket_name = config['BUCKET_NAME']
        self.public_url = config['PUBLIC_URL'].rstrip('/')
        
        # Build API URL
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/r2/buckets/{self.bucket_name}/objects"
        self.headers = {'Authorization': f'Bearer {self.api_token}'}
        
        # File paths
        self.files_folder = Path(config['FILES_FOLDER'])
        self.roam_json = Path(config['ROAM_JSON'])
        self.output_json = Path(config['OUTPUT_JSON'])
        self.progress_file = Path(config['PROGRESS_FILE'])
        
        # Initialize state
        self.mapping = {}
        self.progress = self.load_progress()
        self.local_files_cache = {}
        self.stats = {
            'total_files': 0,
            'uploaded': 0,
            'skipped': 0,
            'failed': 0,
            'links_updated': 0,
            'links_not_found': 0
        }
    
    def validate_config(self):
        """Validate configuration before starting"""
        errors = []
        
        if not self.config['API_TOKEN']:
            errors.append("API_TOKEN is required")
        if not self.config['ACCOUNT_ID']:
            errors.append("ACCOUNT_ID is required")
        if not self.config['BUCKET_NAME']:
            errors.append("BUCKET_NAME is required")
        if not self.config['PUBLIC_URL']:
            errors.append("PUBLIC_URL is required")
        
        if not os.path.exists(self.config['FILES_FOLDER']):
            errors.append(f"Files folder not found: {self.config['FILES_FOLDER']}")
        if not os.path.exists(self.config['ROAM_JSON']):
            errors.append(f"Roam JSON file not found: {self.config['ROAM_JSON']}")
        
        if errors:
            print("❌ Configuration errors:")
            for error in errors:
                print(f"   - {error}")
            sys.exit(1)
    
    def load_progress(self) -> Dict:
        """Load previous progress for resume capability"""
        if self.progress_file.exists():
            print("📂 Found previous progress, resuming...")
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {'uploaded_files': {}, 'mapping': {}}
    
    def save_progress(self):
        """Save current progress"""
        self.progress['mapping'] = self.mapping
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(self.progress, f, indent=2)
    
    def build_file_cache(self):
        """Build a comprehensive cache of all local files for efficient lookup"""
        print("🔍 Building file cache...")
        cache = {}
        
        for file_path in self.files_folder.iterdir():
            if file_path.is_file() and not file_path.name.startswith('.'):
                name = file_path.name
                stem = file_path.stem
                
                # Store multiple keys for flexible lookup
                cache[name] = file_path
                cache[stem] = file_path
                
                # Handle files with suffixes like -image, -12345, etc.
                if '-' in stem:
                    parts = stem.split('-')
                    base_id = parts[0]
                    
                    # Store base ID for lookup
                    if base_id not in cache:
                        cache[base_id] = file_path
                    
                    # For files ending with -image
                    if stem.endswith('-image'):
                        base_without_image = stem[:-6]  # Remove '-image'
                        if base_without_image not in cache:
                            cache[base_without_image] = file_path
        
        self.local_files_cache = cache
        print(f"✅ Cache built with {len(cache)} entries")
    
    def clean_filename(self, filename: str) -> str:
        """Clean problematic characters from filename while maintaining readability"""
        if not self.config['CLEAN_FILENAMES']:
            return filename
        
        # Get file extension
        path = Path(filename)
        stem = path.stem
        ext = path.suffix
        
        # Clean the stem
        stem = stem.replace(' ', '_')
        stem = stem.replace('(', '').replace(')', '')
        stem = stem.replace('[', '').replace(']', '')
        stem = stem.replace(',', '_').replace(';', '_')
        stem = stem.replace('&', 'and')
        stem = stem.replace('#', '')
        stem = re.sub(r'_+', '_', stem)
        stem = stem.strip('_')
        
        return f"{stem}{ext}"
    
    def find_file_for_firebase_id(self, firebase_id: str, extension: str) -> Optional[Path]:
        """
        Find local file that corresponds to a Firebase storage ID.
        Handles various naming patterns Roam uses during export.
        """
        # Direct lookup attempts
        lookup_keys = [
            firebase_id,
            f"{firebase_id}-image",
            f"{firebase_id}{extension}",
            f"{firebase_id}-image{extension}",
        ]
        
        for key in lookup_keys:
            if key in self.local_files_cache:
                file_path = self.local_files_cache[key]
                # Verify extension matches
                if file_path.suffix.lower() == extension.lower():
                    return file_path
        
        # Pattern matching for files with numeric suffixes
        pattern = re.compile(f"^{re.escape(firebase_id)}-\\d+{re.escape(extension)}$", re.IGNORECASE)
        for name, path in self.local_files_cache.items():
            if isinstance(path, Path) and pattern.match(path.name):
                return path
        
        # Pattern matching for files with additional text
        for name, path in self.local_files_cache.items():
            if isinstance(path, Path) and name.startswith(firebase_id) and path.suffix.lower() == extension.lower():
                return path
        
        return None
    
    def upload_file(self, file_path: Path, target_name: str) -> Tuple[bool, str]:
        """Upload a file to R2/S3 storage"""
        try:
            # Read file content
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Determine content type
            ext = file_path.suffix.lower()
            content_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.svg': 'image/svg+xml',
                '.pdf': 'application/pdf',
                '.mp4': 'video/mp4',
                '.mp3': 'audio/mpeg',
                '.wav': 'audio/wav',
                '.doc': 'application/msword',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.xls': 'application/vnd.ms-excel',
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                '.zip': 'application/zip',
            }
            content_type = content_types.get(ext, 'application/octet-stream')
            
            # Prepare upload
            upload_url = f"{self.base_url}/{target_name}"
            upload_headers = {
                **self.headers,
                'Content-Type': content_type
            }
            
            # Perform upload with retries
            for attempt in range(self.config['MAX_RETRIES']):
                try:
                    response = requests.put(
                        upload_url,
                        headers=upload_headers,
                        data=file_content,
                        timeout=60
                    )
                    
                    if response.status_code in [200, 201]:
                        public_url = f"{self.public_url}/{target_name}"
                        return True, public_url
                    elif attempt < self.config['MAX_RETRIES'] - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    else:
                        return False, f"HTTP {response.status_code}: {response.text[:200]}"
                
                except requests.RequestException as e:
                    if attempt < self.config['MAX_RETRIES'] - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return False, str(e)
            
        except Exception as e:
            return False, f"Error reading file: {str(e)}"
        
        return False, "Unknown error"
    
    def process_files(self):
        """Process and upload all files from the export folder"""
        print("\n📤 Starting file upload process...")
        
        # Get all files
        all_files = [f for f in self.files_folder.iterdir() 
                     if f.is_file() and not f.name.startswith('.')]
        
        self.stats['total_files'] = len(all_files)
        
        if not all_files:
            print("⚠️  No files found to process!")
            return
        
        print(f"📊 Found {self.stats['total_files']} files to process")
        print("="*60)
        
        start_time = time.time()
        
        for idx, file_path in enumerate(all_files, 1):
            original_name = file_path.name
            
            # Check if already uploaded
            if original_name in self.progress['uploaded_files']:
                self.stats['skipped'] += 1
                if idx <= 5 or idx % 100 == 0:
                    print(f"[{idx}/{self.stats['total_files']}] ⏭️  {original_name[:50]} (already uploaded)")
                continue
            
            # Determine target name
            if self.config['KEEP_ORIGINAL_NAMES']:
                # Clean filename if it has problematic characters
                if ' ' in original_name or '(' in original_name or ')' in original_name:
                    target_name = self.clean_filename(original_name)
                    print(f"[{idx}/{self.stats['total_files']}] 🔄 {original_name[:40]}")
                    print(f"  → Cleaned: {target_name[:40]}")
                else:
                    target_name = original_name
                    print(f"[{idx}/{self.stats['total_files']}] 📤 {original_name[:50]}")
            else:
                # Generate hash-based name for privacy
                name_hash = hashlib.md5(original_name.encode()).hexdigest()[:12]
                target_name = f"{name_hash}{file_path.suffix}"
                print(f"[{idx}/{self.stats['total_files']}] 🔐 {original_name[:40]} → {target_name}")
            
            # Upload file
            success, result = self.upload_file(file_path, target_name)
            
            if success:
                self.stats['uploaded'] += 1
                
                # Store mapping - use base ID without -image suffix
                base_id = file_path.stem.replace('-image', '')
                self.mapping[base_id] = {
                    'original_name': original_name,
                    'target_name': target_name,
                    'public_url': result,
                    'uploaded_at': datetime.now().isoformat()
                }
                
                # Also store with full stem for edge cases
                self.mapping[file_path.stem] = self.mapping[base_id]
                
                # Mark as uploaded
                self.progress['uploaded_files'][original_name] = target_name
                
                print(f"  ✅ Success! Available at: {result}")
            else:
                self.stats['failed'] += 1
                print(f"  ❌ Failed: {result}")
            
            # Save progress periodically
            if idx % self.config['BATCH_SIZE'] == 0:
                self.save_progress()
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 1
                remaining = (self.stats['total_files'] - idx) / rate if rate > 0 else 0
                print(f"\n⏱️  Progress: {idx}/{self.stats['total_files']} - ETA: {int(remaining/60)} minutes")
                print(f"💾 Progress saved\n")
        
        # Final save
        self.save_progress()
        
        total_time = time.time() - start_time
        print(f"\n✅ Upload complete in {int(total_time/60)} minutes")
    
    def update_roam_json(self):
        """Update all Firebase storage links in the Roam JSON export"""
        print("\n📝 Updating Roam JSON file...")
        
        # Load JSON
        with open(self.roam_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"✅ Loaded {len(data)} pages")
        
        def extract_firebase_id(url: str) -> Tuple[Optional[str], Optional[str]]:
            """Extract file ID and extension from Firebase URL"""
            match = re.search(r'imgs%2Fapp%2F[^%]+%2F([^.]+)\.([^.]+)\.enc', url)
            if match:
                return match.group(1), '.' + match.group(2)
            return None, None
        
        def process_block(block: Dict) -> bool:
            """Process a single block and its children recursively"""
            modified = False
            
            if 'string' in block:
                original = block['string']
                
                # Patterns for different media types
                patterns = [
                    (r'!\[([^\]]*)\]\((https://firebasestorage[^)]+\.enc[^)]*)\)', 'image'),
                    (r'\{\{\[\[pdf\]\]:\s*(https://firebasestorage[^}]+\.enc[^}]*)\}\}', 'pdf'),
                    (r'\{\{\[\[video\]\]:\s*(https://firebasestorage[^}]+\.enc[^}]*)\}\}', 'video'),
                    (r'<(https://firebasestorage[^>]+\.enc[^>]*)>', 'link'),
                ]
                
                for pattern, media_type in patterns:
                    for match in re.finditer(pattern, original, re.IGNORECASE):
                        firebase_url = match.group(2) if media_type == 'image' else match.group(1)
                        firebase_id, extension = extract_firebase_id(firebase_url)
                        
                        if not firebase_id:
                            continue
                        
                        # Find replacement URL
                        replacement_url = None
                        
                        # First check direct mapping
                        if firebase_id in self.mapping:
                            replacement_url = self.mapping[firebase_id]['public_url']
                        else:
                            # Try to find the file
                            local_file = self.find_file_for_firebase_id(firebase_id, extension)
                            if local_file:
                                # Check if it was uploaded with a different name
                                if local_file.name in self.progress['uploaded_files']:
                                    target_name = self.progress['uploaded_files'][local_file.name]
                                    replacement_url = f"{self.public_url}/{target_name}"
                        
                        if replacement_url:
                            # Build replacement text
                            if media_type == 'image':
                                alt_text = match.group(1)
                                new_text = f"![{alt_text}]({replacement_url})"
                            elif media_type == 'pdf':
                                new_text = f"{{{{[[pdf]]: {replacement_url}}}}}"
                            elif media_type == 'video':
                                new_text = f"{{{{[[video]]: {replacement_url}}}}}"
                            else:
                                new_text = f"<{replacement_url}>"
                            
                            block['string'] = block['string'].replace(match.group(0), new_text)
                            self.stats['links_updated'] += 1
                            modified = True
                        else:
                            self.stats['links_not_found'] += 1
            
            # Process children recursively
            if 'children' in block:
                for child in block['children']:
                    if process_block(child):
                        modified = True
            
            return modified
        
        # Process all pages
        pages_modified = 0
        for idx, page in enumerate(data):
            if idx % 100 == 0 and idx > 0:
                print(f"  Processing page {idx}/{len(data)}...")
            
            page_modified = False
            if 'children' in page:
                for child in page['children']:
                    if process_block(child):
                        page_modified = True
            
            if page_modified:
                pages_modified += 1
        
        # Save updated JSON
        print(f"💾 Saving updated JSON...")
        with open(self.output_json, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Updated {self.stats['links_updated']} links in {pages_modified} pages")
        if self.stats['links_not_found'] > 0:
            print(f"⚠️  {self.stats['links_not_found']} links could not be resolved")
        
        print(f"📁 Saved as: {self.output_json}")
    
    def test_connection(self) -> bool:
        """Test connection to Cloudflare R2"""
        print("🔌 Testing API connection...")
        try:
            test_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/r2/buckets"
            response = requests.get(test_url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                print("✅ Connection successful!")
                return True
            elif response.status_code == 403:
                print("❌ Authentication failed - check your API token permissions")
                print("   Ensure the token has 'R2:Edit' permissions")
                return False
            else:
                print(f"❌ Connection failed: HTTP {response.status_code}")
                return False
        
        except Exception as e:
            print(f"❌ Connection error: {e}")
            return False
    
    def print_summary(self):
        """Print final summary of the migration process"""
        print("\n" + "="*60)
        print("📊 MIGRATION SUMMARY")
        print("="*60)
        print(f"Total files found: {self.stats['total_files']}")
        print(f"✅ Successfully uploaded: {self.stats['uploaded']}")
        print(f"⏭️  Skipped (already uploaded): {self.stats['skipped']}")
        print(f"❌ Failed uploads: {self.stats['failed']}")
        print(f"🔗 Links updated in JSON: {self.stats['links_updated']}")
        if self.stats['links_not_found'] > 0:
            print(f"⚠️  Unresolved links: {self.stats['links_not_found']}")
        print("="*60)
    
    def run(self):
        """Execute the complete migration process"""
        print("\n🚀 ROAM RESEARCH ENCRYPTED GRAPH MIGRATION TOOL")
        print("="*60)
        
        # Test connection
        if not self.test_connection():
            return False
        
        # Build file cache
        self.build_file_cache()
        
        # Process files
        self.process_files()
        
        # Update JSON
        if self.stats['uploaded'] > 0 or self.stats['skipped'] > 0:
            self.update_roam_json()
        
        # Print summary
        self.print_summary()
        
        print("\n✅ Migration complete!")
        print("\n📋 Next steps:")
        print("1. Review the updated JSON file")
        print("2. Import it into Roam Research (or another tool)")
        print("3. Verify that all media files are loading correctly")
        print("4. Keep the progress file as backup until confirmed working")
        
        return True

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Migrate Roam Research encrypted graph media files to Cloudflare R2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --token YOUR_TOKEN --account YOUR_ACCOUNT_ID --bucket my-bucket --url https://pub.r2.dev --files ./export/Files --json ./export/backup.json

For more information, visit: https://github.com/rodrigo-kiko/roam-encrypted-migration
        """
    )
    
    # Required arguments
    parser.add_argument('--token', required=True, help='Cloudflare API token with R2 permissions')
    parser.add_argument('--account', required=True, help='Cloudflare account ID')
    parser.add_argument('--bucket', required=True, help='R2 bucket name')
    parser.add_argument('--url', required=True, help='Public URL of the R2 bucket')
    parser.add_argument('--files', required=True, help='Path to "Files and images" folder from Roam export')
    parser.add_argument('--json', required=True, help='Path to the exported Roam JSON file')
    
    # Optional arguments
    parser.add_argument('--output', help='Output path for updated JSON (default: adds _migrated suffix)')
    parser.add_argument('--progress', help='Progress file path (default: same directory as JSON)')
    parser.add_argument('--no-clean', action='store_true', help='Do not clean filenames (keep spaces and special chars)')
    parser.add_argument('--use-hash', action='store_true', help='Use hash-based filenames for privacy')
    parser.add_argument('--batch-size', type=int, default=50, help='Files to process before saving progress (default: 50)')
    
    return parser.parse_args()

def main():
    """Main entry point"""
    args = parse_arguments()
    
    # Build configuration
    config = DEFAULT_CONFIG.copy()
    config['API_TOKEN'] = args.token
    config['ACCOUNT_ID'] = args.account
    config['BUCKET_NAME'] = args.bucket
    config['PUBLIC_URL'] = args.url
    config['FILES_FOLDER'] = args.files
    config['ROAM_JSON'] = args.json
    
    # Set output path
    if args.output:
        config['OUTPUT_JSON'] = args.output
    else:
        json_path = Path(args.json)
        config['OUTPUT_JSON'] = str(json_path.parent / f"{json_path.stem}_migrated.json")
    
    # Set progress file path
    if args.progress:
        config['PROGRESS_FILE'] = args.progress
    else:
        json_path = Path(args.json)
        config['PROGRESS_FILE'] = str(json_path.parent / 'migration_progress.json')
    
    # Apply optional settings
    config['CLEAN_FILENAMES'] = not args.no_clean
    config['KEEP_ORIGINAL_NAMES'] = not args.use_hash
    config['BATCH_SIZE'] = args.batch_size
    
    # Run migration
    try:
        migrator = RoamMediaMigrator(config)
        success = migrator.run()
        sys.exit(0 if success else 1)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Migration interrupted by user")
        print("Progress has been saved. Run again to resume.")
        sys.exit(130)
    
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
