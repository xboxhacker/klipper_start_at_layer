#!/usr/bin/env python3
"""
G-code Layer Skip Script for Klipper with Web Integration and File Browser
"""

import sys
import re
import argparse
import os
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import urllib.parse
import mimetypes
import stat
import subprocess
import socket
import webbrowser
import time

# Global server reference for shutdown
server_instance = None
shutdown_timer = None

class LayerResumeHTTPHandler(BaseHTTPRequestHandler):
    """Custom HTTP handler for the layer resume web interface."""
    
    def do_GET(self):
        """Handle GET requests for serving files."""
        if self.path == '/' or self.path == '/layer_resume_gui.html':
            html_path = '/home/biqu/printer_data/config/START_AT_LAYER/layer_resume_gui.html'
            self.serve_file(html_path)
        else:
            self.send_404()
    
    def do_POST(self):
        """Handle POST requests for API endpoints."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            post_data = self.rfile.read(content_length)
        else:
            post_data = b''
        
        try:
            if self.path == '/api/files':
                self.handle_list_files(post_data)
            elif self.path == '/api/file-content':
                self.handle_get_file_content(post_data)
            elif self.path == '/api/analyze-layers':
                self.handle_analyze_layers(post_data)
            elif self.path == '/api/save-file':
                self.handle_save_file(post_data)
            elif self.path == '/api/queue-print':
                self.handle_queue_print(post_data)
            elif self.path == '/api/download-file':
                self.handle_download_file(post_data)
            elif self.path == '/api/process':
                self.handle_process_gcode(post_data)
            elif self.path == '/api/terminate':
                self.handle_terminate_server(post_data)
            else:
                self.send_404()
                
        except Exception as e:
            print(f"Error handling {self.path}: {str(e)}")
            import traceback
            traceback.print_exc()
            self.send_error_response(str(e))
    
    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
    
    def send_404(self):
        """Send 404 response."""
        self.send_response(404)
        self.send_header('Content-type', 'text/plain')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(b'404 - Not Found')
    
    def serve_file(self, filepath):
        """Serve a static file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
            
        except FileNotFoundError:
            print(f"Error: File not found: {filepath}")
            self.send_response(404)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error_html = f"<html><body><h1>File Not Found</h1><p>Looking for: <code>{filepath}</code></p></body></html>"
            self.wfile.write(error_html.encode('utf-8'))
            
        except Exception as e:
            print(f"Error serving file: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error_html = f"<html><body><h1>Server Error</h1><p>{str(e)}</p></body></html>"
            self.wfile.write(error_html.encode('utf-8'))
    
    def handle_list_files(self, post_data):
        """Handle file listing requests."""
        try:
            if post_data:
                data = json.loads(post_data.decode('utf-8'))
                directory = data.get('path', '/home/biqu/printer_data/gcodes')
            else:
                directory = '/home/biqu/printer_data/gcodes'
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            directory = '/home/biqu/printer_data/gcodes'
        
        # Sanitize and validate path
        directory = os.path.abspath(directory)
        
        if not directory.startswith('/home/biqu'):
            directory = '/home/biqu/printer_data/gcodes'
        
        files = []
        
        try:
            if not os.path.exists(directory):
                directory = '/home/biqu/printer_data/gcodes'
            
            if not os.path.isdir(directory):
                raise ValueError(f"Path is not a directory: {directory}")
            
            # Add parent directory entry if not at root
            if directory != '/home/biqu' and directory != '/':
                files.append({
                    'name': '..',
                    'type': 'directory',
                    'size': 0,
                    'modified': ''
                })
            
            # List directory contents
            try:
                items = os.listdir(directory)
            except PermissionError as e:
                print(f"Permission denied: {e}")
                raise ValueError(f"Permission denied accessing directory: {directory}")
            
            for item in sorted(items):
                # Skip hidden files
                if item.startswith('.'):
                    continue
                    
                item_path = os.path.join(directory, item)
                
                try:
                    stat_info = os.stat(item_path)
                    is_dir = os.path.isdir(item_path)
                    
                    file_info = {
                        'name': item,
                        'type': 'directory' if is_dir else 'file',
                        'size': 0 if is_dir else stat_info.st_size,
                        'modified': datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    # Include all directories and G-code files
                    if is_dir or item.lower().endswith(('.gcode', '.g')):
                        files.append(file_info)
                        
                except (OSError, PermissionError) as e:
                    continue
            
            self.send_json_response(files)
            
        except Exception as e:
            print(f"Error in handle_list_files: {e}")
            import traceback
            traceback.print_exc()
            raise ValueError(f"Failed to list directory '{directory}': {str(e)}")
    
    def handle_get_file_content(self, post_data):
        """Handle file content requests."""
        try:
            data = json.loads(post_data.decode('utf-8'))
            filepath = data.get('filepath', '')
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in request")
        
        # Sanitize path
        filepath = os.path.abspath(filepath)
        if not filepath.startswith('/home/biqu'):
            raise ValueError("Access denied: Invalid file path")
        
        if not os.path.exists(filepath):
            raise ValueError(f"File not found: {filepath}")
        
        if not filepath.lower().endswith(('.gcode', '.g')):
            raise ValueError("Invalid file type - only .gcode and .g files are supported")
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
            
        except Exception as e:
            raise ValueError(f"Failed to read file: {str(e)}")
    
    def handle_analyze_layers(self, post_data):
        """Handle layer analysis requests."""
        try:
            data = json.loads(post_data.decode('utf-8'))
            content = data.get('content', '')
            
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            self.send_error_response("Invalid JSON in request")
            return
        
        try:
            layers = find_layer_change_heights(content)
            
            response_data = {
                'layers': layers,
                'count': len(layers),
                'debug': {
                    'content_length': len(content),
                    'lines_count': len(content.split('\n'))
                }
            }
            
            self.send_json_response(response_data)
            
        except Exception as e:
            print(f"Error analyzing layers: {e}")
            import traceback
            traceback.print_exc()
            self.send_error_response(f"Failed to analyze layers: {str(e)}")
    
    def handle_save_file(self, post_data):
        """Handle file saving requests."""
        try:
            data = json.loads(post_data.decode('utf-8'))
            filename = data.get('filename', '')
            content = data.get('content', '')
            directory = data.get('directory', '/home/biqu/printer_data/gcodes')
        except json.JSONDecodeError:
            self.send_error_response("Invalid JSON in request")
            return
        
        # Sanitize inputs
        directory = os.path.abspath(directory)
        if not directory.startswith('/home/biqu'):
            self.send_error_response("Access denied: Invalid directory path")
            return
        
        # Sanitize filename - be more lenient
        filename = os.path.basename(filename)
        if not filename:
            self.send_error_response("Invalid filename - filename cannot be empty")
            return
        
        # Ensure filename has .gcode extension if it doesn't have one already
        if not filename.lower().endswith(('.gcode', '.g')):
            if '.' in filename:
                # Replace existing extension with .gcode
                filename = os.path.splitext(filename)[0] + '.gcode'
            else:
                # Add .gcode extension
                filename += '.gcode'
        
        filepath = os.path.join(directory, filename)
        
        try:
            # Ensure directory exists
            os.makedirs(directory, exist_ok=True)
            
            # Write file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Set appropriate permissions
            os.chmod(filepath, 0o644)
            
            # Start shutdown timer after successful file save (processing complete)
            schedule_server_shutdown()
            
            self.send_json_response({
                'success': True, 
                'filepath': filepath, 
                'filename': filename,
                'size': len(content.encode('utf-8')),
                'shutdown_in_seconds': 30
            })
            
        except Exception as e:
            print(f"Error saving file: {e}")
            import traceback
            traceback.print_exc()
            self.send_error_response(f"Failed to save file: {str(e)}")
    
    def handle_queue_print(self, post_data):
        """Handle print queue requests."""
        try:
            data = json.loads(post_data.decode('utf-8'))
            filepath = data.get('filepath', '')
            start_print = data.get('start_print', False)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in request")
        
        # Sanitize path
        filepath = os.path.abspath(filepath)
        if not filepath.startswith('/home/biqu'):
            raise ValueError("Access denied: Invalid file path")
        
        if not os.path.exists(filepath):
            raise ValueError(f"File not found: {filepath}")
        
        try:
            filename = os.path.basename(filepath)
            
            # Create a notification that the file is ready for printing
            notification_file = '/tmp/layer_resume_queue.txt'
            with open(notification_file, 'w') as f:
                f.write(f"QUEUED: {filepath}\n")
                f.write(f"TIME: 2025-07-08 14:34:48 UTC\n")
                f.write(f"USER: xboxhacker\n")
                f.write(f"FILENAME: {filename}\n")
            
            self.send_json_response({
                'success': True,
                'filename': filename,
                'method': 'notification',
                'started': False,
                'message': f'File {filename} is ready for printing. Navigate to your printer interface (Mainsail/Fluidd) to start the job.',
                'filepath': filepath
            })
                
        except Exception as e:
            raise ValueError(f"Failed to queue file for printing: {str(e)}")
    
    def handle_download_file(self, post_data):
        """Handle file download requests."""
        try:
            data = json.loads(post_data.decode('utf-8'))
            filepath = data.get('filepath', '')
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in request")
        
        # Sanitize path
        filepath = os.path.abspath(filepath)
        if not filepath.startswith('/home/biqu'):
            raise ValueError("Access denied: Invalid file path")
        
        if not os.path.exists(filepath):
            raise ValueError(f"File not found: {filepath}")
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            filename = os.path.basename(filepath)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/octet-stream')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
            
        except Exception as e:
            raise ValueError(f"Failed to download file: {str(e)}")
    
    def handle_process_gcode(self, post_data):
        """Handle G-code processing requests."""
        try:
            data = json.loads(post_data.decode('utf-8'))
            
            # Extract parameters
            content = data.get('content', '')
            target_z = float(data.get('target_z', 0))
            original_filename = data.get('original_filename', 'unknown.gcode')
            skip_support = data.get('skip_support', False)
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error parsing request: {e}")
            self.send_error_response(f"Invalid request data: {str(e)}")
            return
        
        try:
            # Process the G-code
            result = process_gcode_content(content, target_z, original_filename, skip_support=skip_support)
            
            # Save the processed file
            output_filename = result['filename']
            output_directory = '/home/biqu/printer_data/gcodes'
            output_filepath = os.path.join(output_directory, output_filename)
            
            # Ensure directory exists
            os.makedirs(output_directory, exist_ok=True)
            
            # Write the processed content to file
            with open(output_filepath, 'w', encoding='utf-8') as f:
                f.write(result['content'])
            
            # Set appropriate permissions
            os.chmod(output_filepath, 0o644)
            
            # Format response to match frontend expectations
            response_data = {
                'success': True,
                'output_file': output_filename,
                'filepath': output_filepath,  # Include full path for queue/download
                'processed_content': result['content'],
                'stats': result['stats']
            }
            self.send_json_response(response_data)
            
        except Exception as e:
            print(f"Error processing G-code: {e}")
            import traceback
            traceback.print_exc()
            self.send_error_response(f"Failed to process G-code: {str(e)}")
    
    def handle_terminate_server(self, post_data):
        """Handle immediate server termination requests."""
        try:
            print("\n" + "🛑" * 30)
            print("🛑 IMMEDIATE SERVER TERMINATION REQUESTED")
            print("🛑 Time: 2025-07-08 14:34:48 UTC")
            print("🛑 User: xboxhacker")
            print("🛑 Reason: Manual termination via GUI button")
            print("🛑" * 30)
            
            # Send success response first
            self.send_json_response({
                'success': True,
                'message': 'Server termination initiated',
                'timestamp': '2025-07-08 14:34:48 UTC',
                'user': 'xboxhacker'
            })
            
            # Cancel any existing shutdown timer
            global shutdown_timer
            if shutdown_timer:
                shutdown_timer.cancel()
                print("⏰ Cancelled automatic shutdown timer")
            
            # Schedule immediate shutdown in 2 seconds (gives time for response to send)
            def immediate_shutdown():
                print("🛑 Executing immediate server shutdown...")
                global server_instance
                if server_instance:
                    threading.Thread(target=server_instance.shutdown, daemon=True).start()
                os._exit(0)
            
            shutdown_timer = threading.Timer(2.0, immediate_shutdown)
            shutdown_timer.start()
            
        except Exception as e:
            print(f"Error in server termination: {e}")
            self.send_error_response(f"Failed to terminate server: {str(e)}")
    
    def send_json_response(self, data):
        """Send a JSON response."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response = json.dumps(data, indent=2)
        self.wfile.write(response.encode('utf-8'))
    
    def send_error_response(self, error_message):
        """Send an error response."""
        self.send_response(400)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        error_response = json.dumps({'error': error_message}, indent=2)
        self.wfile.write(error_response.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to suppress default HTTP logging."""
        pass

def schedule_server_shutdown():
    """Schedule server shutdown in 30 seconds."""
    global shutdown_timer, server_instance
    
    # Cancel any existing timer
    if shutdown_timer:
        shutdown_timer.cancel()
    
    def shutdown_server():
        print("\n" + "=" * 50)
        print("🔄 G-code processing completed!")
        print("⏰ Auto-shutdown in 30 seconds...")
        print("📁 Processed file saved successfully")
        print("🛑 Server shutting down automatically")
        print("=" * 50)
        
        if server_instance:
            # Shutdown the server
            threading.Thread(target=server_instance.shutdown, daemon=True).start()
        
        # Exit the program
        os._exit(0)
    
    # Schedule shutdown in 30 seconds
    shutdown_timer = threading.Timer(30.0, shutdown_server)
    shutdown_timer.start()
    
    print("\n" + "⏰" * 20)
    print("🔄 File processing completed successfully!")
    print("⏰ Server will automatically shutdown in 30 seconds")
    print("💾 You can download or queue the file before shutdown")
    print("🛑 Click 'Terminate Server' button for immediate shutdown")
    print("⏰" * 20 + "\n")

def find_layer_change_heights(content):
    """Find all LAYER_CHANGE comments with Z heights.
    
    Args:
        content: G-code content as string or list of lines
    
    Returns:
        List of layer info dictionaries
    """
    layer_lines = []
    lines = content if isinstance(content, list) else content.split('\n')
    
    # Patterns to match LAYER_CHANGE and Z: comments
    layer_change_pattern = re.compile(r';\s*LAYER_CHANGE', re.IGNORECASE)
    z_height_pattern = re.compile(r';\s*Z:\s*(\d+\.?\d*)', re.IGNORECASE)
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for LAYER_CHANGE comment
        if layer_change_pattern.search(line):
            # Look for Z: comment in the next few lines
            for j in range(i + 1, min(i + 5, len(lines))):  # Check next 4 lines
                next_line = lines[j].strip()
                z_match = z_height_pattern.search(next_line)
                
                if z_match:
                    z_height = float(z_match.group(1))
                    layer_info = {
                        'lineNumber': i + 1,  # Line number where LAYER_CHANGE starts
                        'zHeight': z_height,
                        'layerChangeComment': line,
                        'zComment': next_line
                    }
                    layer_lines.append(layer_info)
                    break
        
        i += 1
    
    return layer_lines

def find_layer_lines(content):
    """Find all lines that contain layer height information (Z moves) - LEGACY FALLBACK."""
    layer_lines = []
    z_pattern = re.compile(r'G[01]\s+.*Z(\d+\.?\d*)', re.IGNORECASE)
    
    for i, line in enumerate(content):
        match = z_pattern.search(line)
        if match:
            z_height = float(match.group(1))
            layer_lines.append((i, z_height, line.strip()))
    
    return layer_lines

def find_filament_gcode_start(content):
    """Find the first occurrence of '; Filament gcode'."""
    for i, line in enumerate(content):
        if '; Filament gcode' in line:
            return i
    return None

def find_executable_blocks(content):
    """Find all EXECUTABLE_BLOCK_START and EXECUTABLE_BLOCK_END sections."""
    blocks = []
    start_pattern = re.compile(r';\s*EXECUTABLE_BLOCK_START', re.IGNORECASE)
    end_pattern = re.compile(r';\s*EXECUTABLE_BLOCK_END', re.IGNORECASE)
    
    i = 0
    while i < len(content):
        if start_pattern.search(content[i]):
            start_line = i
            j = i + 1
            while j < len(content):
                if end_pattern.search(content[j]):
                    blocks.append((start_line, j))
                    break
                j += 1
            i = j + 1
        else:
            i += 1
    
    return blocks

def comment_out_all_z_moves_before_target(content, target_line):
    """Comment out ALL Z moves (including in executable blocks) BEFORE the target line."""
    modified_content = content[:]
    z_move_pattern = re.compile(r'^\s*G[01]\s+.*Z', re.IGNORECASE)
    z_moves_commented = 0
    
    # Comment out all Z moves before target line, regardless of context
    for i in range(target_line):
        line = modified_content[i]
        if z_move_pattern.match(line.strip()) and not line.strip().startswith(';'):
            modified_content[i] = '; REMOVED Z-MOVE: ' + line
            z_moves_commented += 1
    
    # Also count executable blocks that were processed (for statistics)
    executable_blocks = find_executable_blocks(content)
    processed_blocks = len([block for block in executable_blocks if block[1] < target_line])
    
    return modified_content, z_moves_commented, processed_blocks

def remove_g28_commands_before_target(content, target_line):
    """Remove or comment out G28 homing commands ONLY BEFORE the target line."""
    modified_content = []
    g28_pattern = re.compile(r'^\s*G28', re.IGNORECASE)
    g28_count = 0
    
    for i, line in enumerate(content):
        if i < target_line and g28_pattern.match(line.strip()):
            modified_content.append('; REMOVED G28: ' + line)
            g28_count += 1
        else:
            modified_content.append(line)
    
    return modified_content, g28_count

def comment_out_layers(content, start_line, end_line):
    """Comment out lines between start_line and end_line."""
    modified_content = content[:]
    
    for i in range(start_line, min(end_line + 1, len(content))):
        line = modified_content[i]
        if not line.strip().startswith(';'):
            modified_content[i] = '; SKIPPED: ' + line
    
    return modified_content

def comment_out_support_sections_after_target(content, target_line):
    """Comment out support and support interface sections after the target layer.
    
    Args:
        content: List of G-code lines
        target_line: Line number (0-based) where target layer starts
    
    Returns:
        Tuple of (modified_content, support_sections_commented)
    """
    modified_content = content[:]
    
    # Patterns to match support layer types (multiple slicer formats)
    # Orca Slicer: ;TYPE:Support, ;TYPE:Support interface
    # PrusaSlicer/SuperSlicer: ;TYPE:SUPPORT, ;TYPE:SUPPORT-INTERFACE
    # Cura: ;TYPE:SUPPORT, ;TYPE:SUPPORT-INTERFACE
    support_type_pattern = re.compile(
        r';\s*TYPE:\s*(?:Support|SUPPORT|Support\s+interface|SUPPORT\s*[-_]?INTERFACE)',
        re.IGNORECASE
    )
    
    # Pattern to match any TYPE: comment
    type_pattern = re.compile(r';\s*TYPE:', re.IGNORECASE)
    
    support_sections_commented = 0
    i = target_line
    
    while i < len(modified_content):
        line = modified_content[i]
        
        # Check if this line starts a support section (check original line, not stripped)
        if support_type_pattern.search(line):
            # Found a support section - comment it out until we find a non-support TYPE
            section_start = i
            
            # Look ahead to find where this support section ends
            # It ends when we find a TYPE: that is NOT support
            j = i + 1
            found_end = False
            while j < len(modified_content):
                next_line = modified_content[j]
                
                # Check if we found a TYPE: comment
                if type_pattern.search(next_line):
                    # If it's not a support type, this is where the support section ends
                    if not support_type_pattern.search(next_line):
                        found_end = True
                        break
                    # If it's another support type, continue (might be support interface after support)
                
                j += 1
            
            # Comment out the support section
            # If we found the end, comment up to (but not including) the next TYPE
            # If we reached end of file, comment to the end
            end_line = j if found_end else len(modified_content)
            for k in range(section_start, end_line):
                # Only comment out non-comment lines
                stripped = modified_content[k].strip()
                if stripped and not stripped.startswith(';'):
                    modified_content[k] = '; SKIPPED SUPPORT: ' + modified_content[k]
            
            support_sections_commented += 1
            i = j  # Continue from after the support section (or end of file)
        else:
            i += 1
    
    return modified_content, support_sections_commented

def find_target_layer_line_by_z_height(layer_changes, target_z):
    """Find the layer change line where the target Z height is reached or exceeded."""
    for layer_info in layer_changes:
        if layer_info['zHeight'] >= target_z:
            return layer_info['lineNumber'] - 1, layer_info['zHeight']  # Convert to 0-based index
    return None, None

def add_resume_header(content, target_z, actual_z, g28_count, z_moves_count, exec_blocks_count, original_filename, skip_support=False, support_sections_commented=0):
    """Add a header comment with resume information."""
    header_lines = [
        "; ================================\n",
        "; MODIFIED GCODE - RESUME PRINT\n",
        f"; Original file: {original_filename}\n",
        f"; Target Z Height: {target_z}mm\n",
        f"; Actual Start Z: {actual_z}mm\n",
        f"; Modified on: 2025-07-08 14:34:48 UTC\n",
        f"; Modified by: xboxhacker\n",
        f"; G28 homing commands removed (before target): {g28_count}\n",
        f"; ALL Z-moves removed (before target): {z_moves_count}\n",
        f"; Executable blocks processed (before target): {exec_blocks_count}\n",
    ]
    
    if skip_support:
        header_lines.append(f"; Support sections skipped after target: {support_sections_commented}\n")
    
    header_lines.extend([
        "; ================================\n",
        "; IMPORTANT: Ensure hotend and bed are at proper temperatures\n",
        "; IMPORTANT: Manually position nozzle near resume point\n",
        "; IMPORTANT: Ensure filament is loaded and primed\n",
        "; IMPORTANT: ALL Z-moves before target layer have been removed\n",
    ])
    
    if skip_support:
        header_lines.append("; IMPORTANT: Support sections after target layer have been skipped\n")
    else:
        header_lines.append("; IMPORTANT: Content AFTER target layer remains unchanged\n")
    
    header_lines.extend([
        "; ================================\n",
        "\n"
    ])
    
    return header_lines + content

def process_gcode_content(content_str, target_z_height, original_filename='unknown.gcode', skip_support=False):
    """Process G-code content and return modified content with statistics.
    
    Args:
        content_str: G-code content as string
        target_z_height: Target Z height to resume from
        original_filename: Original filename
        skip_support: If True, skip printing support sections after target layer
    """
    content = content_str.split('\n')
    
    # Find the start point (first "; Filament gcode")
    filament_start = find_filament_gcode_start(content)
    if filament_start is None:
        filament_start = 0
    
    # Find all layer changes with Z heights (always detect all layers, including support)
    layer_changes = find_layer_change_heights('\n'.join(content))
    if not layer_changes:
        # Fallback to old method if no LAYER_CHANGE comments found
        layer_lines = find_layer_lines(content)
        if not layer_lines:
            raise ValueError("No Z-axis movements or layer changes found in the file.")
        
        # Convert old format to new format for compatibility
        for line_num, z_height, line_content in layer_lines:
            target_line = line_num
            actual_z = z_height
            if z_height >= target_z_height:
                break
        else:
            max_z = max(z for _, z, _ in layer_lines)
            raise ValueError(f"Target Z height {target_z_height}mm not reached. Maximum Z in file: {max_z}mm")
    else:
        # Find the target layer using LAYER_CHANGE comments
        target_line, actual_z = find_target_layer_line_by_z_height(layer_changes, target_z_height)
        if target_line is None:
            max_z = max(layer['zHeight'] for layer in layer_changes)
            raise ValueError(f"Target Z height {target_z_height}mm not reached. Maximum Z in file: {max_z}mm")
    
    # ONLY process content BEFORE the target line
    # Remove G28 commands only before target line
    content, g28_count = remove_g28_commands_before_target(content, target_line)
    
    # Comment out ALL Z moves before target line (including in executable blocks)
    content, z_moves_count, exec_blocks_count = comment_out_all_z_moves_before_target(content, target_line)
    
    # Comment out the specified range (everything before the target layer)
    modified_content = comment_out_layers(content, filament_start, target_line - 1)
    
    # If skip_support is enabled, comment out support sections after the target layer
    support_sections_commented = 0
    if skip_support:
        modified_content, support_sections_commented = comment_out_support_sections_after_target(
            modified_content, target_line
        )
    
    # Add informative header
    modified_content = add_resume_header(modified_content, target_z_height, actual_z, 
                                       g28_count, z_moves_count, exec_blocks_count, original_filename, 
                                       skip_support, support_sections_commented)
    
    # Calculate statistics
    commented_lines = target_line - filament_start
    
    # Generate output filename
    base_name = os.path.splitext(original_filename)[0]
    output_filename = f"{base_name}_resume_Z{target_z_height}mm.gcode"
    
    return {
        'content': '\n'.join(modified_content),
        'filename': output_filename,
            'stats': {
            'g28_count': g28_count,
            'z_moves_count': z_moves_count,
            'exec_blocks_count': exec_blocks_count,
            'commented_lines': commented_lines,
            'actual_z': actual_z,
            'target_z': target_z_height,
            'original_filename': original_filename,
            'total_lines': len(modified_content),
            'target_line': target_line,
            'support_sections_skipped': support_sections_commented if skip_support else 0
        }
    }

def find_available_port(start_port=8081, max_attempts=20):
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            # Test if port is available
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            
            if result != 0:  # Port is available
                return port
        except:
            continue
    
    raise RuntimeError(f"No available ports found in range {start_port}-{start_port + max_attempts - 1}")

def open_browser_tab(url, delay=3):
    """Open browser tab with better compatibility for various environments."""
    def delayed_open():
        time.sleep(delay)
        try:
            webbrowser.open_new_tab(url)
        except Exception as e:
            print(f"❌ Browser opening error: {e}")
    
    thread = threading.Thread(target=delayed_open, daemon=True)
    thread.start()

def start_web_server(port=8081, open_browser_tab_flag=True):
    """Start the web server for the GUI."""
    global server_instance
    
    # Always try to find an available port, starting from the requested port
    try:
        available_port = find_available_port(port, max_attempts=20)
    except RuntimeError as e:
        print(f"❌ Error: {e}")
        return None
    
    # Bind to all interfaces so it's accessible from network
    server_address = ('0.0.0.0', available_port)
    
    try:
        httpd = HTTPServer(server_address, LayerResumeHTTPHandler)
        server_instance = httpd  # Store global reference for shutdown
    except OSError as e:
        print(f"❌ Failed to bind to port {available_port}: {e}")
        return None
    
    print("=" * 70)
    print("🔄 Layer Resume Web GUI Server Starting")
    print("=" * 70)
    print(f"📅 Date: 2025-07-08 14:34:48 UTC")
    print(f"👤 User: xboxhacker")
    print(f"🌐 Server: http://0.0.0.0:{available_port}")
    print(f"📁 G-codes Directory: /home/biqu/printer_data/gcodes")
    print(f"🏠 Home Directory: /home/biqu")
    print(f"📄 HTML File: /home/biqu/printer_data/config/START_AT_LAYER/layer_resume_gui.html")
    print("⏰ Auto-shutdown: Server will close 30 seconds after processing")
    print("🛑 Manual shutdown: Use 'Terminate Server' button in GUI")
    print("=" * 70)
    
    # Print access URLs
    localhost_url = f"http://localhost:{available_port}/layer_resume_gui.html"
    veho_url = f"http://veho.local:{available_port}/layer_resume_gui.html"
    
    print("🌍 Access the Layer Resume GUI at:")
    print(f"   {veho_url}")
    print(f"   {localhost_url}")
    
    if available_port != port:
        print(f"⚠️  Note: Using port {available_port} instead of {port} (port was busy)")
    print("=" * 70)
    
    # Open browser automatically if requested
    if open_browser_tab_flag:
        gui_url = f"http://localhost:{available_port}/layer_resume_gui.html"
        open_browser_tab(gui_url, delay=3)
        print(f"🚀 Browser tab will open automatically in 3 seconds...")
    
    print("⚠️  Press Ctrl+C to stop the server manually")
    print("⏰ Server will auto-shutdown 30 seconds after file processing")
    print("🛑 Or use 'Terminate Server' button in GUI for immediate shutdown")
    print("")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user.")
    
    return available_port

def main():
    parser = argparse.ArgumentParser(
        description="G-code Layer Resume Tool with Web GUI and File Browser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage:
  Web GUI:        python3 start_at_layer_web.py --web
  No Browser:     python3 start_at_layer_web.py --web --no-browser
  Custom Port:    python3 start_at_layer_web.py --web --port 8082

Setup Instructions:
  1. Ensure layer_resume_gui.html is in /home/biqu/printer_data/config/START_AT_LAYER/
  2. Run: python3 start_at_layer_web.py --web
  3. Browser opens automatically to: http://localhost:8081/layer_resume_gui.html
  4. Also accessible at: http://veho.local:8081/layer_resume_gui.html

Port Selection:
  - Default starts at 8081
  - Automatically finds next available port if busy
  - Tests up to 20 ports (8081-8100)
  
Features:
  - LAYER_CHANGE and Z: comment parsing for accurate layer detection
  - Auto browser tab opening
  - Network accessible interface
  - File browser for G-code selection
  - Fallback to G-code Z moves if no LAYER_CHANGE comments found
  - ONLY modifies content BEFORE selected layer height
  - Comments out ALL Z-moves before target layer (including in executable blocks)
  - Auto-shutdown 30 seconds after file processing
  - Manual termination button in GUI
        """
    )
    
    parser.add_argument('--web', action='store_true',
                       help='Start web server for GUI interface')
    parser.add_argument('--no-browser', action='store_true',
                       help='Do not open browser automatically')
    parser.add_argument('--port', type=int, default=8081,
                       help='Starting port for web server (default: 8081, auto-finds if busy)')
    
    args = parser.parse_args()
    
    if args.web:
        actual_port = start_web_server(args.port, open_browser_tab_flag=not args.no_browser)
        if actual_port:
            veho_url = f"http://veho.local:{actual_port}/layer_resume_gui.html"
            print(f'\n🔗 Layer Resume GUI: {veho_url}')
        return
    
    # Default behavior
    print("G-code Layer Resume Tool")
    print("Use --web flag to start the web interface")
    print("Default starting port is 8081 (auto-finds available)")
    print("Example: python3 start_at_layer_web.py --web")

if __name__ == "__main__":
    exit(main())
