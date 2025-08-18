# Roam Research Encrypted Graph Migration Tool

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Roam Research](https://img.shields.io/badge/Roam-Research-orange)](https://roamresearch.com/)

A comprehensive solution for migrating encrypted Roam Research graphs while preserving all media files and attachments. This tool solves the long-standing issue of broken media links when exporting encrypted Roam graphs.

## 🎯 The Problem

When you export an encrypted Roam Research graph:
1. The backup is decrypted during export (which is good)
2. You also have to manually export all media files (images, PDFs, etc.) to a local folder
3. **BUT** the links in the JSON still point to encrypted Firebase URLs (`.enc` files)
4. When you import this backup, all media files appear broken

This has been a major pain point for the Roam community for years, preventing users from:
- Creating true backups of encrypted graphs
- Migrating between tools
- Forking graphs with media
- Moving from encrypted to unencrypted graphs

## ✨ The Solution

This tool:
1. **Uploads** all exported media files to Cloudflare R2 (or any S3-compatible storage)
2. **Processes** the exported JSON to replace all Firebase URLs with your new URLs
3. **Handles** all edge cases including:
   - Files with special naming patterns (`-image`, numeric suffixes like `-44306`)
   - Files with spaces and special characters
   - PDFs, images, videos, and other attachments
   - Large graphs with thousands of files
4. **Maintains** traceability by keeping original filenames (or using secure hashes)
5. **Supports** resume capability if the process is interrupted

## 🚀 Quick Start

### Prerequisites

- Python 3.7 or higher
- A Cloudflare account with R2 enabled (or compatible S3 storage)
- Your exported Roam Research backup

### Installation

```bash
# Clone the repository
git clone https://github.com/rodrigo-kiko/roam-encrypted-migration.git
cd roam-encrypted-migration

# Install dependencies
pip install requests
```

### Setting up Cloudflare R2

1. **Create a Cloudflare account** (if you don't have one)
2. **Enable R2**:
   - Go to R2 in your Cloudflare dashboard
   - Create a new bucket (e.g., `roam-media`)
   - Enable public access: Settings → R2.dev subdomain → Allow access
   - Copy the public URL (e.g., `https://pub-xxxxx.r2.dev`)

3. **Create an API token**:
   - Go to My Profile → API Tokens
   - Create Token → Custom Token
   - Permissions: Account - Workers R2 Storage:Edit
   - Copy the token (you'll only see it once!)

4. **Get your Account ID**:
   - It's in the URL when you're in the Cloudflare dashboard
   - Or in the right sidebar of your account home

### Basic Usage

```bash
python roam_migration.py \
  --token YOUR_CLOUDFLARE_TOKEN \
  --account YOUR_ACCOUNT_ID \
  --bucket your-bucket-name \
  --url https://pub-xxxxx.r2.dev \
  --files "/path/to/Files and images" \
  --json /path/to/your-backup.json
```

## 📖 Detailed Guide

### Step 1: Export Your Roam Graph

1. In Roam Research, click the three dots menu → Export All
2. Choose "JSON" format
3. Select "Export all"
4. Download and extract the ZIP file
5. In Roam Research, click the three dots menu → Settings → Files → Download All Files

You'll get a folder structure like:
```
Roam Export/
├── Your-Graph-Name-2024-08-16.json
└── Files and images/
    ├── image1.png
    ├── document.pdf
    └── ... (all your media files)
```

### Step 2: Run the Migration

```bash
# Full example with real paths
python roam_migration.py \
  --token abcd1234567890 \
  --account xyz987654321 \
  --bucket roam-backup \
  --url https://pub-abc123.r2.dev \
  --files "/Users/john/Downloads/Roam Export/Files and images" \
  --json "/Users/john/Downloads/Roam Export/MyGraph-2024-08-16.json"
```

The tool will:
1. Test the API connection
2. Build a cache of all local files
3. Upload each file (showing progress)
4. Update all links in the JSON
5. Save the migrated JSON file
6. Display a summary

### Step 3: Import the Migrated Graph

1. Create a new graph in Roam Research (or your target tool)
2. Import the `*_migrated.json` file
3. All your media files should now load correctly!

## 🎯 Use Cases

### 1. Backup Encrypted Graphs
Create a true backup of your encrypted Roam graph with all media intact.

### 2. Migrate to Other Tools
Export from Roam and import to:
- Obsidian (with media links working)
- Logseq
- Tana
- RemNote
- Athens Research
- Any tool that accepts Roam JSON

### 3. Fork Graphs
Create a copy of your graph with all media files accessible.

### 4. Decrypt Graphs
Move from an encrypted graph to an unencrypted one without losing media.

### 5. Archive Projects
Create a complete archive of a project graph with all attachments.

## 🐛 Troubleshooting

### "API Token Invalid"
- Ensure your token has `Workers R2 Storage:Edit` permission
- Check that you're using the correct account ID

### "Files not found"
- Verify the path to "Files and images" folder is correct
- Ensure you're using the extracted folder, not the ZIP

### "Links still broken after import"
- Check that your R2 bucket has public access enabled
- Verify the public URL is correct
- Test a file URL directly in your browser

### Large Graphs (1000+ files)
- The tool handles large graphs efficiently
- Expect ~30-60 minutes for 2000+ files
- Progress is saved every 50 files by default

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- The Roam Research community for identifying and discussing this issue
- Cloudflare for providing an excellent R2 service
- Contributors and testers from the Roam Slack and Reddit communities

## 📬 Support

- **Issues**: [GitHub Issues](https://github.com/rodrigo-kiko/roam-encrypted-migration/issues)
- **Discussions**: [GitHub Discussions](https://github.com/rodrigo-kiko/roam-encrypted-migration/discussions)
- **Community**: [Roam Research Slack](https://roamresearch.slack.com)

---

**Made with ❤️ for the all the "#TFT" (Tools for Thought) community**
