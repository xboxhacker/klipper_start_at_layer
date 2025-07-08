# G-code Layer Resume Tool

A web-based GUI tool for resuming failed 3D prints at specific layer heights. Designed for Klipper firmware with Mainsail/Fluidd integration.

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.6+-green.svg)
![License](https://img.shields.io/badge/license-MIT-yellow.svg)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)

## 🚀 Features

- **Web-based GUI** - Access from any browser on your network
- **Intelligent Layer Detection** - Supports both `LAYER_CHANGE` comments and fallback Z-move detection
- **Interactive File Browser** - Navigate and select G-code files visually
- **Layer Preview** - See all available layers before processing
- **Dropdown Layer Selection** - Choose exact layer from dropdown or enter Z height manually
- **Safe Processing** - Only modifies content BEFORE target layer, preserves everything after
- **Auto-shutdown** - Server automatically closes 30 seconds after processing
- **Network Accessible** - Works with headless printer setups
- **Mainsail/Fluidd Compatible** - Perfect for modern Klipper installations

**YOUR KLIPPER SYSTEM WILL BE UNRESPONIVE WHILE THE SERVER IS RUNNING**
  
## 📋 What It Does

When a 3D print fails, this tool helps you resume from a specific layer by:

1. **Commenting out early layers** - Skips already printed content
2. **Removing G28 homing commands** - Prevents axis crashes during resume
3. **Disabling Z-moves** - Comments out problematic Z-axis movements before target layer
4. **Preserving layer content** - Keeps all content after target layer completely unchanged
5. **Adding safety headers** - Includes important resume instructions in output file

## 🛠️ Installation

### Prerequisites

- Linux system (Raspberry Pi, etc.)
- Python 3.6 or higher
- Klipper firmware (recommended)
- Mainsail or Fluidd web interface (recommended)

### Setup Instructions

1. **Create directory structure:** (Change this DIR for your device)
```bash
mkdir -p /home/biqu/printer_data/config/START_AT_LAYER
cd /home/biqu/printer_data/config/START_AT_LAYER
```

2. **Download the files:**
```bash
# Download main script
wget https://raw.githubusercontent.com/username/repo/main/start_at_layer_web.py
chmod +x start_at_layer_web.py

# Download HTML interface
wget https://raw.githubusercontent.com/username/repo/main/layer_resume_gui.html
```

3. **Verify file structure:**
```
/home/biqu/printer_data/config/START_AT_LAYER/
├── start_at_layer_web.py
└── layer_resume_gui.html
```

4. **Test installation:**
```bash
python3 start_at_layer_web.py --web
```

## 🎯 Usage

### Quick Start

1. **Start the web server:**
```bash
cd /home/biqu/printer_data/config/START_AT_LAYER
python3 start_at_layer_web.py --web
```

2. **Access the GUI:**
   - Local: `http://localhost:8081/layer_resume_gui.html`
   - Network: `http://your-printer-ip:8081/layer_resume_gui.html`
   - Hostname: `http://mainsail.local:8081/layer_resume_gui.html`

3. **Process your G-code:**
   - Click "📁 Browse Files" to select your failed print file
   - Choose target layer from dropdown or enter Z height manually
   - Click "🚀 Process G-code"
   - Download or queue the modified file for printing

### Command Line Options

```bash
# Start with browser auto-open (default)
python3 start_at_layer_web.py --web

# Start without opening browser
python3 start_at_layer_web.py --web --no-browser

# Use custom port
python3 start_at_layer_web.py --web --port 8082

# Show help
python3 start_at_layer_web.py --help
```

### Web Interface Guide

#### 1. File Selection
- Use the file browser to navigate to your G-code files
- Default directory: `/home/biqu/printer_data/gcodes`
- Click on directories to navigate, files to select

#### 2. Layer Selection
- **Dropdown Method**: Choose from detected layers in dropdown
- **Manual Entry**: Enter specific Z height in millimeters
- **Find Nearest**: Click to find closest layer to entered Z height

#### 3. Processing
- Click "📋 Preview Layers" to see all available layers
- Click "🚀 Process G-code" to generate resume file
- Server automatically shuts down 30 seconds after processing

#### 4. Output Options
- **🖨️ Queue for Printing**: Prepare file for printer interface
- **💾 Download File**: Download processed G-code to your device
- **🔄 Process Another File**: Reset interface for new file

## 🔧 Configuration

### Directory Paths

The tool restricts access to safe directories:
- **G-codes**: `/home/biqu/printer_data/gcodes`
- **Home**: `/home/biqu`
- **Subdirectories**: Any subdirectory within `/home/biqu`

### Port Configuration

- **Default Port**: 8081
- **Auto-discovery**: Automatically finds available port if 8081 is busy
- **Range**: Tests ports 8081-8100
- **Custom Port**: Use `--port` flag to specify

### File Types

Supported G-code file extensions:
- `.gcode`
- `.g`

## 🔍 Technical Details

### Layer Detection Methods

1. **Primary**: `LAYER_CHANGE` comments with `Z:` values
```gcode
; LAYER_CHANGE
; Z:5.2
```

2. **Fallback**: G0/G1 Z-moves
```gcode
G1 Z5.2 F720
```

### Processing Algorithm

1. **Find Target Layer**: Locate layer at or above target Z height
2. **Remove G28 Commands**: Comment out homing before target
3. **Disable Z-moves**: Comment out ALL Z-moves before target layer
4. **Skip Early Content**: Comment out content from filament start to target
5. **Preserve Later Content**: Keep everything after target unchanged
6. **Add Header**: Include resume instructions and statistics

### Generated Header Example

```gcode
; ================================
; MODIFIED GCODE - RESUME PRINT
; Original file: my_print.gcode
; Target Z Height: 5.2mm
; Actual Start Z: 5.2mm
; G28 homing commands removed (before target): 3
; ALL Z-moves removed (before target): 15
; Executable blocks processed (before target): 2
; ================================
; IMPORTANT: Ensure hotend and bed are at proper temperatures
; IMPORTANT: Manually position nozzle near resume point
; IMPORTANT: Ensure filament is loaded and primed
; IMPORTANT: ALL Z-moves before target layer have been removed
; IMPORTANT: Content AFTER target layer remains unchanged
; ================================
```

## 🤖 Mainsail Integration

### Creating a Mainsail Macro

Add this to your `printer.cfg`:

```ini
[gcode_shell_command start_layer_resume]
command: python3 /home/biqu/printer_data/config/START_AT_LAYER/start_at_layer_web.py --web --no-browser
timeout: 300.0
verbose: True

[gcode_macro LAYER_RESUME_GUI]
description: Start Layer Resume Web GUI
gcode:
    RESPOND MSG="Starting Layer Resume GUI..."
    RUN_SHELL_COMMAND CMD=start_layer_resume
    RESPOND MSG="Layer Resume GUI: http://mainsail.local:8081"
```

### Usage in Mainsail

1. Go to Mainsail interface
2. Navigate to "Macros" section  
3. Click "LAYER_RESUME_GUI" button
4. Click the provided link to access GUI

## 🛡️ Security & Safety

### File Access Restrictions

- **Path Validation**: Only allows access to `/home/biqu` directory tree
- **Extension Filtering**: Only processes `.gcode` and `.g` files
- **Path Sanitization**: Prevents directory traversal attacks

### Print Resume Safety Checklist

Before starting a resumed print:

- ✅ **Heat hotend and bed** to proper temperatures FIRST
- ✅ **Manually home axes** if needed (G28 X, G28 Y separately)  
- ✅ **Position nozzle** near the resume point manually
- ✅ **Load filament** and ensure extruder is primed
- ✅ **Monitor first layers** carefully after resume
- ⚠️ **Z-axis homing disabled** - position Z manually if needed

### Network Security

- **Local Network Only**: Server binds to all interfaces but should be behind firewall
- **No Authentication**: Intended for trusted local networks only
- **Auto-shutdown**: Server automatically closes after processing

## 🔧 Troubleshooting

### Common Issues

#### "File not found" error
```bash
# Check file path
ls -la /home/biqu/printer_data/config/START_AT_LAYER/
# Ensure files exist and have correct permissions
chmod +x start_at_layer_web.py
```

#### "Port already in use"
```bash
# Tool automatically finds next available port
# Or specify custom port:
python3 start_at_layer_web.py --web --port 8082
```

#### "No layers found"
- File may not have `LAYER_CHANGE` comments
- Tool will fallback to detecting Z-moves
- Ensure G-code file is properly formatted

#### "Permission denied" 
```bash
# Fix file permissions
chmod +x start_at_layer_web.py
chmod 644 layer_resume_gui.html
```

#### Browser won't open automatically
- Use `--no-browser` flag and navigate manually
- Check if display server is available
- Access via network URL instead

### Debug Mode

For troubleshooting, check console output:
```bash
python3 start_at_layer_web.py --web
# Server logs will show detailed error information
```

### Log Files

Check these locations for additional logs:
- **Queue notifications**: `/tmp/layer_resume_queue.txt`
- **Console output**: Real-time server logs

## 📁 File Structure

```
/home/biqu/printer_data/config/START_AT_LAYER/
├── start_at_layer_web.py          # Main Python web server
├── layer_resume_gui.html          # Web interface HTML
└── README.md                      # This documentation

/home/biqu/printer_data/gcodes/    # G-code files location
├── original_print.gcode           # Your original files
└── original_print_resume_Z5.2mm.gcode  # Generated resume files

/tmp/
└── layer_resume_queue.txt         # Queue notification file
```

## 🚀 Advanced Usage

### Batch Processing

For automation, the tool can be integrated with scripts:

```bash
#!/bin/bash
# Start server in background
python3 start_at_layer_web.py --web --no-browser &
SERVER_PID=$!

# Wait for server to start
sleep 3

# Use curl for API calls
curl -X POST http://localhost:8081/api/process \
  -H "Content-Type: application/json" \
  -d '{"content":"...gcode...","target_z":5.2,"original_filename":"test.gcode"}'

# Cleanup
kill $SERVER_PID
```

### Custom Directory Configuration

Modify the script to use different directories by editing these variables:

```python
# In start_at_layer_web.py
DEFAULT_GCODES_DIR = '/home/biqu/printer_data/gcodes'
HTML_PATH = '/home/biqu/printer_data/config/START_AT_LAYER/layer_resume_gui.html'
```

## 🤝 Contributing

### Development Setup

1. **Clone repository:**
```bash
git clone https://github.com/username/layer-resume-tool.git
cd layer-resume-tool
```

2. **Create test environment:**
```bash
mkdir -p test_data/gcodes
# Add sample G-code files for testing
```

3. **Run development server:**
```bash
python3 start_at_layer_web.py --web --port 8082
```

### Code Structure

- **HTTP Handler**: `LayerResumeHTTPHandler` class
- **G-code Processing**: `process_gcode_content()` function  
- **Layer Detection**: `find_layer_change_heights()` function
- **Server Management**: `start_web_server()` function

### Testing

```bash
# Test layer detection
python3 -c "
from start_at_layer_web import find_layer_change_heights
with open('test.gcode', 'r') as f:
    content = f.read()
    layers = find_layer_change_heights(content)
    print(f'Found {len(layers)} layers')
"
```

## 📄 License

MIT License

Copyright (c) 2025 xboxhacker

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## 📈 Changelog

### Version 1.0.0 (2025-07-08 14:20:32 UTC)

**Initial Release**
- ✅ Web-based GUI interface
- ✅ LAYER_CHANGE comment detection
- ✅ Fallback Z-move detection
- ✅ Interactive file browser
- ✅ Layer dropdown selection
- ✅ Auto-shutdown after processing
- ✅ G28 command removal
- ✅ Z-move commenting before target layer
- ✅ Safe file processing (preserves content after target)
- ✅ Network accessibility
- ✅ Mainsail/Fluidd compatibility
- ✅ Mobile-friendly interface
- ✅ Download and queue functionality

**Author:** xboxhacker  
**Last Updated:** 2025-07-08 14:20:32 UTC

---

## 🆘 Support

If you encounter issues:

1. **Check troubleshooting section** above
2. **Review console output** for error messages
3. **Verify file permissions** and directory structure
4. **Test with simple G-code file** first
5. **Create GitHub issue** with detailed error description

**Happy printing! 🖨️**
