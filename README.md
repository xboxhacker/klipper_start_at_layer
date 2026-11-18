# G-code Layer Resume Tool

A web-based GUI tool for resuming failed 3D prints at specific layer heights. Designed for Klipper firmware with Mainsail/Fluidd integration.

![Version](https://img.shields.io/badge/version-1.7.2-blue.svg)
![Python](https://img.shields.io/badge/python-3.6+-green.svg)
![License](https://img.shields.io/badge/license-MIT-yellow.svg)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)

## 🚀 Features

- **Web-based GUI** - Access from any browser on your network
- **Intelligent Layer Detection** - Supports both `LAYER_CHANGE` comments and fallback Z-move detection
- **Interactive File Browser** - Navigate and select G-code files visually
- **Layer Preview** - See all available layers before processing
- **Dropdown Layer Selection** - Choose exact layer from dropdown or enter Z height manually
- **Support Material Skipping** - Option to skip only the first support block after resume (subsequent layers print supports normally)
- **Cancel Processing** - Cancel button to stop processing if needed
- **Clear File** - Easy way to clear current file and start fresh
- **Auto-Load Most Recent Print** - Automatically loads the most recently modified G-code file on page load
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

- Linux system (Raspberry Pi, BTT Pi, etc.)
- Python 3.6 or higher
- Klipper firmware
- MoonRaker
- Mainsail or Fluidd web interface (recommended)

### Setup Instructions

Paths use the **home directory of the user running the script** (e.g. `/home/pi` on Raspberry Pi, `/home/biqu` on BTT, or your Klipper host username). The tool uses `~/printer_data` under that home directory.

1. **Create directory structure:** Run as the same user that runs Klipper (e.g. `pi`, `biqu`, or your host user).
```bash
mkdir -p ~/printer_data/config/START_AT_LAYER
cd ~/printer_data/config/START_AT_LAYER
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
~/printer_data/config/START_AT_LAYER/
├── start_at_layer_web.py
└── layer_resume_gui.html
```

4. **Test installation:**
```bash
python3 start_at_layer_web.py --web
```

### 🛠️ ALTERNATIVE INSTALLATION (recommended)

1. **Create directory `START_AT_LAYER` In Mainsail/Fluidd in the `Config` Directory**

2. **Upload or Drag & Drop files to the `config/START_AT_LAYER` Directory**



## 🎯 Usage

### Quick Start

1. **Start the web server:** (from your START_AT_LAYER directory, or use the full path)
```bash
cd ~/printer_data/config/START_AT_LAYER
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
- **Auto-Load**: Most recent print file is automatically loaded when the page opens
- **Most Recent Button**: Click "⭐ Most Recent Print" to reload the most recent file
- Use the file browser to navigate to your G-code files
- Default directory: `~/printer_data/gcodes` (detected automatically from the host)
- Click on directories to navigate, files to select

#### 2. Layer Selection
- **Dropdown Method**: Choose from detected layers in dropdown
- **Manual Entry**: Enter specific Z height in millimeters
- **Find Nearest**: Click to find closest layer to entered Z height
- **Support Skipping**: Checkbox to skip only the first support block on the resume layer (rest print normally)

#### 3. Processing
- Click "📋 Preview Layers" to see all available layers
- Click "🚀 Process G-code" to generate resume file
- Use "❌ Cancel Processing" button to stop processing if needed
- Server automatically shuts down 30 seconds after processing

#### 4. File Management
- **✖️ Clear File**: Button to clear current file and reset interface
- Automatically clears previous file when selecting a new one

#### 5. Output Options
- **🖨️ Queue for Printing**: Prepare file for printer interface
- **💾 Download File**: Download processed G-code to your device
- **🔄 Process Another File**: Reset interface for new file

## 🔧 Configuration

### Directory Paths

The tool uses the **home directory of the user running the script** (same as Klipper). Paths are resolved at runtime—no editing for different hosts.
- **G-codes**: `~/printer_data/gcodes`
- **Home**: `~` (your Klipper user’s home, e.g. `/home/pi`, `/home/biqu`)
- **Access**: Restricted to that home directory tree for security

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
2. **Resume start sequence**: Insert at the **target layer** (not the top of the file):
   - **SET_KINEMATIC_POSITION Z=**: tell Klipper the bed/nozzle is already at the resume height (no Z motion)
   - **Extrusion mode**: M82 or M83 from the original start gcode
   - **SET_PRESSURE_ADVANCE**: first occurrence from the original file
   - **XY travel only**: move to resume X/Y with no Z on the line
   - **G11**: unretract
3. **Remove G28 / PRINT_START**: Comment out homing and start macros before target (these send a moving bed to Z=0)
4. **Disable Z-moves**: Comment out ALL Z-moves before target layer; strip Z from G0/G1 on the resume layer until the next layer change
5. **Skip Early Content**: Comment out executable start gcode from `EXECUTABLE_BLOCK_START` through the target layer
6. **Skip First Support Block** (optional): If enabled, comments out only the first support section after target layer; subsequent layers print supports normally
7. **Preserve Later Content**: Keep everything after target unchanged (except first support block if skipped)
8. **Add Header**: Include resume instructions and statistics

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
; First support section skipped after target: 1
; ================================
; IMPORTANT: Ensure hotend and bed are at proper temperatures
; IMPORTANT: Manually position nozzle near resume point
; IMPORTANT: Ensure filament is loaded and primed
; IMPORTANT: ALL Z-moves before target layer have been removed
; IMPORTANT: First support block after target layer skipped, rest print normally
; IMPORTANT: Content AFTER target layer remains unchanged
; ================================
```

## 🤖 Mainsail Integration

### Creating a Mainsail Macro

Add this to your `printer.cfg`:

```ini
###############################################################
# Resume failed print with a "start at layer" option
###############################################################

[gcode_shell_command start_layer_resume]
command: python3 ~/printer_data/config/START_AT_LAYER/start_at_layer_web.py --web --no-browser
timeout: 1000.0  #Server timeout to kill the server
verbose: True

[gcode_macro LAYER_RESUME_GUI]
description: Start Layer Resume Web GUI
gcode:
    RESPOND MSG="Starting Layer Resume GUI..."
    RESPOND MSG="Layer Resume GUI: http://YOURPRINTER.local:8081"
    RESPOND MSG="Open this link to use the GUI. Shut down the GUI server when you're done."
    RUN_SHELL_COMMAND CMD=start_layer_resume
    
```

### Usage in Mainsail

1. Go to Mainsail interface
2. Navigate to "Macros" section  
3. Click "LAYER_RESUME_GUI" button
4. Click the provided link to access GUI

## 🛡️ Security & Safety

### File Access Restrictions

- **Path Validation**: Only allows access to the home directory of the user running the script
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
# Check file path (use your actual path, e.g. /home/pi or /home/biqu)
ls -la ~/printer_data/config/START_AT_LAYER/
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

#### "Target Z height exceeds maximum"
- The entered Z height is higher than the maximum in the file
- Use the dropdown to select from available layers
- Or enter a Z height within the file's range (shown in error message)

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
~/printer_data/config/START_AT_LAYER/
├── start_at_layer_web.py          # Main Python web server
├── layer_resume_gui.html          # Web interface HTML
└── README.md                      # This documentation

~/printer_data/gcodes/             # G-code files (path depends on host user)
├── original_print.gcode           # Your original files
└── original_print_resume_Z5.2mm.gcode  # Generated resume files

/tmp/
└── layer_resume_queue.txt         # Queue notification file
```

`~` is the home directory of the user running the script (e.g. `/home/pi`, `/home/biqu`).

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

### How Paths Work

The script uses `os.path.expanduser('~')` so it runs correctly on any Klipper host. Run it as the **same user that runs Klipper** (e.g. `pi`, `biqu`). Paths are:

- **Home**: `~` (e.g. `/home/pi`, `/home/biqu`)
- **G-codes**: `~/printer_data/gcodes`
- **Config**: `~/printer_data/config/START_AT_LAYER/`

No path editing is needed when moving between hosts.

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

### Version 1.7.2 (2026-08-31)

**XY actually travels after you home X and Y**
- ✅ **SET_KINEMATIC_POSITION Z only** - Setting kinematic X/Y to the print position made `G1 X Y` a no-move after G28 X/Y (firmware thought it was already there)
- ✅ **Travel to first live XY** - After skip-support, move to the first remaining print coordinate, not the hop onto skipped support

**Author:** xboxhacker  
**Last Updated:** 2026-08-31

---

### Version 1.7.1 (2026-08-31)

**Pause while printing a resume file**
- ✅ **SET_KINEMATIC_POSITION X Y Z** - Marks all axes homed so Mainsail/Klipper `PAUSE` can park. If only Z was set, `PAUSE` often aborted with "Must home axis" and the print kept running
- ✅ **M400 after resume XY** - Lets pause interrupt after the entry move
- ⚠️ Your `PAUSE` macro must lift Z with **G91** (relative). After resume the file is in **G90**; `G1 Z10` without G91 sends a moving bed toward Z=10 and looks like it will not stop

**Author:** xboxhacker  
**Last Updated:** 2026-08-31

---

### Version 1.7.0 (2026-08-31)

**VEHO / moving-bed: do not move Z at resume start**
- ✅ **No G1 Z at resume** - Bed stays at the physical height you already set
- ✅ **SET_KINEMATIC_POSITION Z=** - Tells Klipper the resume height without commanding motion
- ✅ **PRINT_START / mesh / gantry macros commented** - These were still running (before filament start gcode) and homing the bed to Z=0
- ✅ **Skip from EXECUTABLE_BLOCK_START** - Entire machine start block is skipped, not only from `; filament start gcode`
- ✅ **Z stripped from resume-layer moves** until the next LAYER_CHANGE; later layers still use normal Z hops

**Author:** xboxhacker  
**Last Updated:** 2026-08-31

---

### Version 1.6.0 (2026-06-18)

**Deterministic, crash-safe resume entry**
- ✅ **Controlled start sequence** - At the resume layer the tool now emits an explicit ordered sequence: (1) `G90`, extrusion mode + pressure advance, `G92 E0`; (2) raise Z to 5mm above the resume layer; (3) move XY to the resume position at the safe height; (4) lower Z to the print layer; (5) `G11` unretract
- ✅ **XY never moves at print height** - The slicer's own lead-in (retract/wipe/lift/travel/prime) is detected and commented as `; RESUME-REPLACED:` so it cannot move XY before Z clearance
- ✅ **Real travel target** - Picks the first pure-travel XY (move without extrusion) as the resume position, ignoring retract/wipe moves

**Author:** xboxhacker  
**Last Updated:** 2026-06-18

---

### Version 1.5.0 (2026-06-18)

**Resume safety**
- ✅ **Z clearance before XY** - Injects `G90` and `G1 Z(target+5mm)` at the resume layer before any XY motion to avoid gantry crashes
- ✅ **Slicer metadata preserved** - Resume preamble and comment header stay after HEADER/thumbnail blocks so Mainsail can open files
- ✅ **Version display** - GUI shows `GUI vX.Y.Z · PY vX.Y.Z`; backend exposes `GET /api/version`

**Fixes**
- 🔧 Output filename keeps original characters (no sanitization)
- 🔧 Large-file processing: read from disk, stream layer analysis, no full G-code in API response

**Author:** xboxhacker  
**Last Updated:** 2026-06-18

---

### Version 1.4.0 (2025-02-18)

**Resume retraction & flow (firmware retraction)**
- ✅ **Resume preamble** - Injects a short block at the start of the modified file (after custom header): extrusion mode (M82/M83) from original, first SET_PRESSURE_ADVANCE from original, and G11 (unretract) so Klipper has correct pressure advance and a known unretracted state before the first move
- ✅ **Extrusion mode detection** - Uses the same M82 or M83 as the original start gcode so absolute vs relative extrusion matches the file (avoids over-extrusion when file is absolute)

**Improvements**
- 🔧 Fixes bad retraction and flow when resuming with firmware retraction (G10/G11) by re-establishing PA and unretract state

**Author:** xboxhacker  
**Last Updated:** 2025-02-18

---

### Version 1.3.0 (2025-01-XX)

**Code Review & Fixes**
- 🔧 **Output filename fix** - Use basename for output file when original path is full path
- 🔧 **Support skip logic** - Verified first-support-only skip works correctly for resume flow

**Verification**
- ✅ Target layer detection (LAYER_CHANGE + fallback Z-moves)
- ✅ G28 removal before target only
- ✅ Z-move commenting before target only  
- ✅ Content before target commented (filament_start to target_line-1)
- ✅ Target layer and all content after preserved (except first support block if skipped)
- ✅ First support section skip only, subsequent layers print supports normally

**Author:** xboxhacker  
**Last Updated:** 2025-01-XX

---

### Version 1.2.0 (2025-01-XX)

**New Features**
- ✅ **Auto-Load Most Recent Print** - Automatically loads the most recently modified G-code file when the page opens
- ✅ **Most Recent Print Button** - Quick button to reload the most recent print file
- ✅ **Smart File Detection** - Recursively searches gcodes directory and excludes resume files

**Improvements**
- 🔧 Better UX for resuming failed prints (99.999% of the time you want the most recent file)
- 🔧 Faster workflow - no need to browse for the file you just printed

**Author:** xboxhacker  
**Last Updated:** 2025-01-XX

---

### Version 1.1.0 (2025-01-XX)

**New Features**
- ✅ **Support Material Skipping** - Option to skip only the first support block after resume (subsequent layers print normally)
- ✅ **Cancel Processing Button** - Ability to cancel processing if wrong file or settings selected
- ✅ **Clear File Button** - Easy way to clear current file and start fresh
- ✅ **Automatic State Clearing** - Automatically clears previous file data when selecting a new file
- ✅ **Improved Error Messages** - Better error messages with helpful suggestions
- ✅ **File Auto-Save** - Processed files are automatically saved to disk

**Improvements**
- 🔧 Better handling of file state management
- 🔧 Improved support layer detection (Orca Slicer, PrusaSlicer, SuperSlicer, Cura)
- 🔧 Enhanced UI feedback during processing
- 🔧 Better validation of target Z heights

**Author:** xboxhacker  
**Last Updated:** 2025-01-XX

---

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
