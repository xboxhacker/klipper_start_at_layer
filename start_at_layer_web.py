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
import stat
import shutil
import socket
import webbrowser
import time

# Global server reference for shutdown
server_instance = None
shutdown_timer = None

# Paths: use the home directory of the user running the script (works for pi, biqu, or any Klipper host)
_HOME_DIR = os.path.expanduser('~')
_PRINTER_DATA_DIR = os.path.join(_HOME_DIR, 'printer_data')
_GCODES_DIR = os.path.join(_PRINTER_DATA_DIR, 'gcodes')
_CONFIG_DIR = os.path.join(_PRINTER_DATA_DIR, 'config')
_START_AT_LAYER_DIR = os.path.join(_CONFIG_DIR, 'START_AT_LAYER')
_CUSTOM_HEADER_FILE = os.path.join(_START_AT_LAYER_DIR, 'custom_header_gcode.txt')
APP_VERSION = '1.7.2'


# Compiled patterns reused across processing
_LAYER_CHANGE_RE = re.compile(r';\s*LAYER_CHANGE', re.IGNORECASE)
_Z_HEIGHT_RE = re.compile(r';\s*Z:\s*(\d+\.?\d*)', re.IGNORECASE)
_Z_MOVE_RE = re.compile(r'^\s*G[01]\s+.*Z', re.IGNORECASE)
_G28_RE = re.compile(r'^\s*G28', re.IGNORECASE)
_START_MACRO_RE = re.compile(
    r'^\s*(PRINT_START|START_PRINT|BED_MESH_CALIBRATE|QUAD_GANTRY_LEVEL|'
    r'Z_TILT_ADJUST|G29|HOME_Z|G34)\b',
    re.IGNORECASE,
)
_Z_AXIS_RE = re.compile(r'\s+Z-?(?:\d+\.?\d*|\.\d+)', re.IGNORECASE)
_LEGACY_Z_RE = re.compile(r'G[01]\s+.*Z(\d+\.?\d*)', re.IGNORECASE)
_EXEC_BLOCK_START_RE = re.compile(r';\s*EXECUTABLE_BLOCK_START', re.IGNORECASE)
_EXEC_BLOCK_END_RE = re.compile(r';\s*EXECUTABLE_BLOCK_END', re.IGNORECASE)


_SUPPORT_TYPE_RE = re.compile(
    r';\s*TYPE:\s*(?:Support|SUPPORT|Support\s+interface|SUPPORT\s*[-_]?INTERFACE)',
    re.IGNORECASE
)
_TYPE_COMMENT_RE = re.compile(r';\s*TYPE:', re.IGNORECASE)


def read_gcode_file(filepath):
    """Read and validate a G-code file. Returns file content or raises ValueError."""
    filepath = os.path.abspath(filepath)
    if not filepath.startswith(_HOME_DIR):
        raise ValueError("Access denied: Invalid file path")
    if not os.path.exists(filepath):
        raise ValueError(f"File not found: {filepath}")
    if not filepath.lower().endswith(('.gcode', '.g')):
        raise ValueError("Invalid file type - only .gcode and .g files are supported")
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def sanitize_gcode_basename(name):
    """Remove characters that break Mainsail/Moonraker URLs and HTTP download headers."""
    for ch in '&?#%<>:"|\\':
        name = name.replace(ch, '_')
    return name.strip() or 'resume'


def content_disposition_attachment(filename):
    """RFC 5987-safe Content-Disposition for filenames with special characters."""
    ascii_name = filename.encode('ascii', 'ignore').decode('ascii') or 'resume.gcode'
    ascii_name = ascii_name.replace('"', '')
    encoded = urllib.parse.quote(filename)
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


class LayerResumeHTTPHandler(BaseHTTPRequestHandler):
    """Custom HTTP handler for the layer resume web interface."""
    
    def do_GET(self):
        """Handle GET requests for serving files."""
        if self.path == '/' or self.path == '/layer_resume_gui.html':
            html_path = os.path.join(_START_AT_LAYER_DIR, 'layer_resume_gui.html')
            self.serve_file(html_path)
        elif self.path == '/api/paths':
            self.send_json_response({
                'home': _HOME_DIR,
                'gcodes': _GCODES_DIR,
                'printer_data': _PRINTER_DATA_DIR,
            })
        elif self.path == '/api/version':
            self.send_json_response({'version': APP_VERSION})
        elif self.path == '/api/custom-header':
            self.handle_get_custom_header()
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
            elif self.path == '/api/most-recent-file':
                self.handle_most_recent_file(post_data)
            elif self.path == '/api/custom-header-save':
                self.handle_save_custom_header(post_data)
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
                directory = data.get('path') or _GCODES_DIR
            else:
                directory = _GCODES_DIR
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            directory = _GCODES_DIR
        
        # Sanitize and validate path (restrict to user's home directory)
        directory = os.path.abspath(directory) if directory else _GCODES_DIR
        if not directory.startswith(_HOME_DIR):
            directory = _GCODES_DIR
        
        files = []
        
        try:
            if not os.path.exists(directory):
                directory = _GCODES_DIR
            
            if not os.path.isdir(directory):
                raise ValueError(f"Path is not a directory: {directory}")
            
            # Add parent directory entry if not at root
            if directory != _HOME_DIR and directory != '/':
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
        
        try:
            content = read_gcode_file(filepath)
            
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
            filepath = data.get('filepath', '')
            content = data.get('content') or ''
            
            if filepath:
                filepath = os.path.abspath(filepath)
                if not filepath.startswith(_HOME_DIR):
                    self.send_error_response("Access denied: Invalid file path")
                    return
                if not os.path.exists(filepath):
                    self.send_error_response(f"File not found: {filepath}")
                    return
                layers = find_layer_change_heights_from_file(filepath)
                file_size = os.path.getsize(filepath)
                line_count = None
            elif not content:
                self.send_error_response("No file or content provided for layer analysis")
                return
            else:
                layers = find_layer_change_heights(content)
                file_size = len(content)
                line_count = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
            
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            self.send_error_response("Invalid JSON in request")
            return
        except ValueError as e:
            self.send_error_response(str(e))
            return
        
        try:
            if line_count is None:
                line_count = _count_file_lines(filepath)
            response_data = {
                'layers': layers,
                'count': len(layers),
                'debug': {
                    'content_length': file_size,
                    'lines_count': line_count
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
            content = data.get('content') or ''
            directory = data.get('directory', _GCODES_DIR)
        except json.JSONDecodeError:
            self.send_error_response("Invalid JSON in request")
            return
        
        # Sanitize inputs
        directory = os.path.abspath(directory)
        if not directory.startswith(_HOME_DIR):
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
        if not filepath.startswith(_HOME_DIR):
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
        if not filepath.startswith(_HOME_DIR):
            raise ValueError("Access denied: Invalid file path")
        
        if not os.path.exists(filepath):
            raise ValueError(f"File not found: {filepath}")
        
        try:
            filename = os.path.basename(filepath)
            file_size = os.path.getsize(filepath)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/octet-stream')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Disposition', content_disposition_attachment(filename))
            self.send_header('Content-Length', str(file_size))
            self.end_headers()
            
            with open(filepath, 'rb') as f:
                shutil.copyfileobj(f, self.wfile)
            
        except BrokenPipeError:
            print("Client disconnected during file download")
        except Exception as e:
            raise ValueError(f"Failed to download file: {str(e)}")
    
    def handle_process_gcode(self, post_data):
        """Handle G-code processing requests."""
        try:
            data = json.loads(post_data.decode('utf-8'))
            
            # Extract parameters
            target_z = float(data.get('target_z', 0))
            original_filename = data.get('original_filename', 'unknown.gcode')
            filepath = data.get('filepath') or original_filename
            skip_support = data.get('skip_support', False)
            custom_header = (data.get('custom_header') or '').strip()
            content = data.get('content') or ''
            
            # Prefer reading from disk (large files, or when frontend did not send content)
            if filepath and filepath != 'unknown.gcode':
                try:
                    content = read_gcode_file(filepath)
                except ValueError as e:
                    if not content:
                        self.send_error_response(f"Failed to read G-code file: {e}")
                        return
            
            if not content:
                self.send_error_response(
                    "No G-code content provided. Select a file first or provide a valid filepath."
                )
                return
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error parsing request: {e}")
            self.send_error_response(f"Invalid request data: {str(e)}")
            return
        
        try:
            # Process the G-code and write directly to disk (avoids huge in-memory response).
            # Let process_gcode_content build the sanitized output path/filename.
            os.makedirs(_GCODES_DIR, exist_ok=True)
            result = process_gcode_content(
                content, target_z, original_filename,
                skip_support=skip_support,
                custom_header=custom_header
            )
            
            response_data = {
                'success': True,
                'output_file': result['filename'],
                'filepath': result['filepath'],
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
    
    def handle_most_recent_file(self, post_data):
        """Handle requests for the most recently modified G-code file."""
        try:
            if post_data:
                data = json.loads(post_data.decode('utf-8'))
                directory = data.get('path') or _GCODES_DIR
            else:
                directory = _GCODES_DIR
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            directory = _GCODES_DIR
        
        # Sanitize and validate path (restrict to user's home directory)
        directory = os.path.abspath(directory)
        if not directory.startswith(_HOME_DIR):
            directory = _GCODES_DIR
        
        try:
            if not os.path.exists(directory):
                directory = _GCODES_DIR
            
            if not os.path.isdir(directory):
                raise ValueError(f"Path is not a directory: {directory}")
            
            # Find all G-code files recursively
            gcode_files = []
            for root, dirs, files in os.walk(directory):
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for filename in files:
                    # Skip hidden files and resume files (they're generated, not original prints)
                    if filename.startswith('.') or '_resume_' in filename:
                        continue
                    
                    if filename.lower().endswith(('.gcode', '.g')):
                        filepath = os.path.join(root, filename)
                        try:
                            stat_info = os.stat(filepath)
                            gcode_files.append({
                                'name': filename,
                                'path': filepath,
                                'type': 'file',
                                'size': stat_info.st_size,
                                'modified': stat_info.st_mtime,  # Keep as timestamp for sorting
                                'modified_str': datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                            })
                        except (OSError, PermissionError):
                            continue
            
            if not gcode_files:
                self.send_json_response({
                    'success': False,
                    'message': 'No G-code files found'
                })
                return
            
            # Sort by modification time (most recent first)
            gcode_files.sort(key=lambda x: x['modified'], reverse=True)
            most_recent = gcode_files[0]
            
            # Convert timestamp back to string for response
            most_recent['modified'] = most_recent['modified_str']
            del most_recent['modified_str']
            
            self.send_json_response({
                'success': True,
                'file': most_recent
            })
            
        except Exception as e:
            print(f"Error finding most recent file: {e}")
            import traceback
            traceback.print_exc()
            self.send_error_response(f"Failed to find most recent file: {str(e)}")
    
    def handle_get_custom_header(self):
        """Serve custom header G-code from config file. Creates empty file if missing."""
        try:
            if os.path.isfile(_CUSTOM_HEADER_FILE):
                with open(_CUSTOM_HEADER_FILE, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = ''
            self.send_json_response({'content': content})
        except Exception as e:
            print(f"Error reading custom header: {e}")
            self.send_json_response({'content': ''})

    def handle_save_custom_header(self, post_data):
        """Save custom header G-code to config file."""
        try:
            data = json.loads(post_data.decode('utf-8'))
            content = data.get('content') or ''
        except json.JSONDecodeError:
            self.send_error_response("Invalid JSON")
            return
        try:
            os.makedirs(_START_AT_LAYER_DIR, exist_ok=True)
            with open(_CUSTOM_HEADER_FILE, 'w', encoding='utf-8') as f:
                f.write(content)
            os.chmod(_CUSTOM_HEADER_FILE, 0o644)
            self.send_json_response({'success': True, 'message': 'Custom header saved'})
        except Exception as e:
            print(f"Error saving custom header: {e}")
            self.send_error_response(f"Failed to save: {str(e)}")

    def send_json_response(self, data):
        """Send a JSON response."""
        try:
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        except BrokenPipeError:
            print("Client disconnected before response could be sent")
    
    def send_error_response(self, error_message):
        """Send an error response."""
        try:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': error_message}).encode('utf-8'))
        except BrokenPipeError:
            print("Client disconnected before error response could be sent")
    
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

def _count_file_lines(filepath):
    """Count lines in a file without loading it all into memory."""
    count = 0
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for count, _ in enumerate(f, 1):
            pass
    return count


def find_layer_change_heights_from_file(filepath):
    """Stream a G-code file and find LAYER_CHANGE entries without loading the whole file."""
    layers = []
    pending = None
    i = 0
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            stripped = line.strip()
            if pending is not None:
                pn, pcomment, checked = pending
                checked += 1
                z_match = _Z_HEIGHT_RE.search(stripped)
                if z_match:
                    layers.append({
                        'lineNumber': pn + 1,
                        'zHeight': float(z_match.group(1)),
                        'layerChangeComment': pcomment,
                        'zComment': stripped
                    })
                    pending = None
                elif checked >= 4:
                    pending = None
                else:
                    pending = (pn, pcomment, checked)
            elif _LAYER_CHANGE_RE.search(stripped):
                pending = (i, stripped, 0)
            i += 1
    return layers


def find_layer_change_heights(content):
    """Find all LAYER_CHANGE comments with Z heights.
    
    Args:
        content: G-code content as string or list of lines
    
    Returns:
        List of layer info dictionaries
    """
    layer_lines = []
    lines = content if isinstance(content, list) else content.splitlines()
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if _LAYER_CHANGE_RE.search(line):
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j].strip()
                z_match = _Z_HEIGHT_RE.search(next_line)
                
                if z_match:
                    layer_lines.append({
                        'lineNumber': i + 1,
                        'zHeight': float(z_match.group(1)),
                        'layerChangeComment': line,
                        'zComment': next_line
                    })
                    break
        
        i += 1
    
    return layer_lines


def find_target_layer_line(content, target_z_height):
    """Single-pass search for the first layer at or above target Z.
    Returns (0-based index, z) on success, or (None, max_z_or_None) if not found.
    """
    max_z = None
    i = 0
    while i < len(content):
        if _LAYER_CHANGE_RE.search(content[i]):
            for j in range(i + 1, min(i + 5, len(content))):
                z_match = _Z_HEIGHT_RE.search(content[j])
                if z_match:
                    z_height = float(z_match.group(1))
                    max_z = z_height if max_z is None else max(max_z, z_height)
                    if z_height >= target_z_height:
                        return i, z_height
                    break
        i += 1
    return None, max_z


def find_target_layer_line_legacy(content, target_z_height):
    """Fallback: find first Z move at or above target. Returns (index, z) or (None, max_z)."""
    max_z = 0.0
    for i, line in enumerate(content):
        match = _LEGACY_Z_RE.search(line)
        if match:
            z_height = float(match.group(1))
            max_z = max(max_z, z_height)
            if z_height >= target_z_height:
                return i, z_height
    return None, max_z if max_z > 0 else None


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
    """Find the first occurrence of filament start gcode comment (OrcaSlicer/PrusaSlicer)."""
    for i, line in enumerate(content):
        lower = line.lower()
        if '; filament gcode' in lower or '; filament start gcode' in lower:
            return i
    return None


def find_skip_start(content):
    """First line of machine start gcode to skip (before target layer).

    Prefer EXECUTABLE_BLOCK_START so PRINT_START / homing before '; filament start gcode'
    cannot still run and send the bed to Z=0.
    """
    for i, line in enumerate(content):
        if _EXEC_BLOCK_START_RE.search(line):
            return i
    filament = find_filament_gcode_start(content)
    return filament if filament is not None else 0


def find_metadata_end_line(content):
    """Line index before executable gcode; keeps slicer HEADER/thumbnail blocks at file start."""
    for i, line in enumerate(content):
        if _EXEC_BLOCK_START_RE.search(line):
            return i
    for i, line in enumerate(content):
        if 'HEADER_BLOCK_END' in line:
            return i + 1
    return 0


def insert_lines_at(content, index, lines):
    """Insert lines into content at index (each line normalized with newline)."""
    for offset, line in enumerate(lines):
        content.insert(index + offset, line if line.endswith('\n') else line + '\n')


def split_gcode_lines(text):
    """Split a G-code snippet into lines for insertion."""
    if not text or not text.strip():
        return []
    return [line if line.endswith('\n') else line + '\n' for line in text.splitlines()]


def find_executable_blocks(content, max_line=None):
    """Find EXECUTABLE_BLOCK_START/END sections up to max_line."""
    blocks = []
    limit = len(content) if max_line is None else min(max_line, len(content))
    
    i = 0
    while i < limit:
        if _EXEC_BLOCK_START_RE.search(content[i]):
            start_line = i
            j = i + 1
            while j < len(content):
                if _EXEC_BLOCK_END_RE.search(content[j]):
                    blocks.append((start_line, j))
                    break
                j += 1
            i = j + 1
        else:
            i += 1
    
    return blocks

def comment_out_all_z_moves_before_target(content, target_line):
    """Comment out ALL Z moves BEFORE the target line (in place)."""
    z_moves_commented = 0
    
    for i in range(target_line):
        line = content[i]
        stripped = line.strip()
        if stripped and not stripped.startswith(';') and _Z_MOVE_RE.match(stripped):
            content[i] = '; REMOVED Z-MOVE: ' + line
            z_moves_commented += 1
    
    executable_blocks = find_executable_blocks(content, target_line)
    processed_blocks = len([block for block in executable_blocks if block[1] < target_line])
    
    return content, z_moves_commented, processed_blocks

def remove_g28_commands_before_target(content, target_line):
    """Comment out G28 homing commands BEFORE the target line (in place)."""
    g28_count = 0
    
    for i in range(target_line):
        line = content[i]
        stripped = line.strip()
        if stripped and not stripped.startswith(';') and _G28_RE.match(stripped):
            content[i] = '; REMOVED G28: ' + line
            g28_count += 1
    
    return content, g28_count

def comment_out_start_macros_before_target(content, target_line):
    """Comment PRINT_START / mesh / gantry macros that would home or drop Z."""
    count = 0
    for i in range(target_line):
        stripped = content[i].strip()
        if stripped and not stripped.startswith(';') and _START_MACRO_RE.match(stripped):
            content[i] = '; REMOVED START MACRO: ' + content[i]
            count += 1
    return content, count

def strip_z_from_moves(content, start_line, end_line):
    """Remove Z from G0/G1 in [start_line, end_line) so the bed is not commanded."""
    stripped_count = 0
    g_move = re.compile(r'^\s*G[01]\b', re.IGNORECASE)
    for i in range(start_line, min(end_line, len(content))):
        line = content[i]
        stripped = line.strip()
        if not stripped or stripped.startswith(';') or not g_move.match(stripped):
            continue
        if _Z_AXIS_RE.search(line):
            content[i] = _Z_AXIS_RE.sub('', line)
            stripped_count += 1
    return stripped_count

def find_next_layer_change(content, after_index):
    """Index of the next LAYER_CHANGE after after_index, or len(content)."""
    for i in range(after_index + 1, len(content)):
        if _LAYER_CHANGE_RE.search(content[i]):
            return i
    return len(content)

def filter_custom_header_no_z(custom_header):
    """Drop G28 and Z moves from custom header so it cannot move the bed."""
    if not custom_header or not custom_header.strip():
        return ''
    kept = []
    for line in custom_header.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(';'):
            kept.append(line)
            continue
        if _G28_RE.match(stripped) or _START_MACRO_RE.match(stripped):
            continue
        if re.match(r'^\s*SET_KINEMATIC_POSITION\b', stripped, re.IGNORECASE):
            if re.search(r'\b[XY]\s*=', stripped, re.IGNORECASE):
                continue
        if re.match(r'^\s*G[01]\b', stripped, re.IGNORECASE) and _Z_AXIS_RE.search(line):
            line = _Z_AXIS_RE.sub('', line)
            if not re.search(r'\b[XYE]\s*-?(?:\d+\.?\d*|\.\d+)', line, re.IGNORECASE):
                continue
        kept.append(line)
    return '\n'.join(kept)

def comment_out_layers(content, start_line, end_line):
    """Comment out lines between start_line and end_line (in place)."""
    for i in range(start_line, min(end_line + 1, len(content))):
        line = content[i]
        if line.strip() and not line.strip().startswith(';'):
            content[i] = '; SKIPPED: ' + line
    
    return content

def comment_out_support_sections_after_target(content, target_line):
    """Comment out ONLY THE FIRST support section after the target layer.
    
    Skips the first support block (Support + Support interface) right after the
    target layer, then prints supports normally for all subsequent layers.
    
    Layer order: Layer Change -> Supports -> Inner Wall -> Outer Wall -> Infill -> (repeat)
    We skip only the first "Supports" block after resume.
    
    Args:
        content: List of G-code lines
        target_line: Line number (0-based) where target layer starts
    
    Returns:
        Tuple of (modified_content, support_sections_commented)
    """
    modified_content = content
    
    support_sections_commented = 0
    i = target_line
    
    while i < len(modified_content):
        line = modified_content[i]
        
        # Check if this line starts a support section
        if _SUPPORT_TYPE_RE.search(line):
            # Found the FIRST support section - comment it out until we find a non-support TYPE
            section_start = i
            
            # Look ahead to find where this support section ends
            # It ends when we find a TYPE: that is NOT support (e.g. Inner Wall, Outer Wall)
            j = i + 1
            found_end = False
            while j < len(modified_content):
                next_line = modified_content[j]
                
                if _TYPE_COMMENT_RE.search(next_line):
                    if not _SUPPORT_TYPE_RE.search(next_line):
                        found_end = True
                        break
                
                j += 1
            
            # Comment out this first support section only
            end_line = j if found_end else len(modified_content)
            for k in range(section_start, end_line):
                stripped = modified_content[k].strip()
                if stripped and not stripped.startswith(';'):
                    modified_content[k] = '; SKIPPED SUPPORT: ' + modified_content[k]
            
            support_sections_commented += 1
            # STOP HERE - we only skip the first support section, then print supports normally
            break
        else:
            i += 1
    
    return modified_content, support_sections_commented

def extract_resume_preamble(content_lines, target_line):
    """Extract lines that must run at resume for retraction/flow: extrusion mode (M82/M83),
    first SET_PRESSURE_ADVANCE, and G11 (unretract). Scans original content before target_line only.
    Returns a string (possibly empty) to prepend before printing.
    """
    preamble = []
    # Use same extrusion mode as original start gcode so E values are interpreted correctly
    m82_m83_pattern = re.compile(r'^\s*(M82|M83)\b', re.IGNORECASE)
    for i in range(min(target_line, len(content_lines))):
        line = content_lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith(';'):
            continue
        m = m82_m83_pattern.search(stripped)
        if m:
            preamble.append(f"{m.group(1).upper()} ; extrusion mode from original (resume)")
            break
    set_pa_pattern = re.compile(r'^\s*SET_PRESSURE_ADVANCE\b', re.IGNORECASE)
    for i in range(min(target_line, len(content_lines))):
        line = content_lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith(';'):
            continue
        if set_pa_pattern.search(stripped):
            preamble.append(stripped)
            break
    # Ensure firmware retraction is in unretracted state before first move
    preamble.append('G11 ; unretract (resume)')
    return '\n'.join(preamble) + '\n'

def extract_resume_state(content_lines, target_line):
    """Find extrusion mode (M82/M83) and first SET_PRESSURE_ADVANCE before the target line.
    Returns (mode_line, pa_line) where each may be None.
    """
    mode_line = None
    pa_line = None
    m_re = re.compile(r'^\s*(M82|M83)\b', re.IGNORECASE)
    pa_re = re.compile(r'^\s*SET_PRESSURE_ADVANCE\b', re.IGNORECASE)
    for i in range(min(target_line, len(content_lines))):
        stripped = content_lines[i].strip()
        if not stripped or stripped.startswith(';'):
            continue
        if mode_line is None:
            m = m_re.search(stripped)
            if m:
                mode_line = m.group(1).upper()
        if pa_line is None and pa_re.search(stripped):
            pa_line = stripped
    return mode_line, pa_line

def find_layer_entry_region(content, target_line, max_scan=600):
    """Locate the slicer's lead-in region for the target layer (retract/wipe/lift/travel/prime).
    
    Returns (entry_start, entry_end, travel_x, travel_y) or None.
    - entry_start: first executable line after the LAYER_CHANGE comment header
    - entry_end: index of the first ';TYPE:' line (start of actual feature printing)
    - travel_x/travel_y: first pure-travel XY target (G0/G1 with X and Y, no E) in the region
    """
    n = len(content)
    end = min(n, target_line + max_scan)
    _num = r'-?(?:\d+\.?\d*|\.\d+)'
    type_re = re.compile(r';\s*TYPE:', re.IGNORECASE)
    move_re = re.compile(r'^\s*G[01]\b', re.IGNORECASE)
    x_re = re.compile(r'\bX(' + _num + r')', re.IGNORECASE)
    y_re = re.compile(r'\bY(' + _num + r')', re.IGNORECASE)
    e_re = re.compile(r'\bE(' + _num + r')', re.IGNORECASE)
    
    entry_end = None
    for j in range(target_line, end):
        if type_re.search(content[j]):
            entry_end = j
            break
    if entry_end is None:
        return None
    
    entry_start = None
    for j in range(target_line, entry_end):
        stripped = content[j].strip()
        if stripped and not stripped.startswith(';'):
            entry_start = j
            break
    if entry_start is None:
        return None
    
    # Prefer a pure travel move (X and Y, no extrusion) = move to the resume position
    travel_x = travel_y = None
    for j in range(entry_start, entry_end):
        stripped = content[j].strip()
        if not stripped or stripped.startswith(';') or not move_re.match(stripped):
            continue
        xm, ym, em = x_re.search(stripped), y_re.search(stripped), e_re.search(stripped)
        if xm and ym and em is None:
            travel_x, travel_y = float(xm.group(1)), float(ym.group(1))
            break
    # Fallback: first XY move of any kind
    if travel_x is None:
        for j in range(entry_start, entry_end):
            stripped = content[j].strip()
            if not stripped or stripped.startswith(';') or not move_re.match(stripped):
                continue
            xm, ym = x_re.search(stripped), y_re.search(stripped)
            if xm and ym:
                travel_x, travel_y = float(xm.group(1)), float(ym.group(1))
                break
    
    return entry_start, entry_end, travel_x, travel_y

def find_first_live_xy(content, start_line, max_scan=12000):
    """First executable G0/G1 that still has X and Y after skipping/commenting."""
    _num = r'-?(?:\d+\.?\d*|\.\d+)'
    x_re = re.compile(r'\bX(' + _num + r')', re.IGNORECASE)
    y_re = re.compile(r'\bY(' + _num + r')', re.IGNORECASE)
    move_re = re.compile(r'^\s*G[01]\b', re.IGNORECASE)
    end = min(len(content), start_line + max_scan)
    for j in range(start_line, end):
        stripped = content[j].strip()
        if not stripped or stripped.startswith(';') or not move_re.match(stripped):
            continue
        xm, ym = x_re.search(stripped), y_re.search(stripped)
        if xm and ym:
            return float(xm.group(1)), float(ym.group(1))
    return None, None

def build_resume_start_sequence(actual_z, mode_line, pa_line, custom_header, travel_x, travel_y, xy_feed=9000):
    """Resume entry that does not move Z/bed.

    SET_KINEMATIC_POSITION is Z only. Do not lie about X/Y: if the user homed XY,
    setting kinematic XY to the print position makes G1 X Y a no-move (stays at home).
    """
    seq = [
        '; === RESUME START SEQUENCE (Layer Resume Tool) ===\n',
        '; Z/bed is NOT moved. Stay at current physical height.\n',
        '; Home X and Y before starting. Do not SET_KINEMATIC_POSITION on X/Y.\n',
        '; PAUSE: PAUSE macros must hop Z with G91 (relative). G90 G1 Z10 would drive the bed to Z=10.\n',
        f'SET_KINEMATIC_POSITION Z={actual_z:.3f} '
        '; tell Klipper Z is already at resume height (no motion)\n',
        'G90 ; absolute XY positioning\n',
    ]
    if mode_line:
        seq.append(f'{mode_line} ; extrusion mode from original\n')
    if pa_line:
        seq.append(pa_line + '\n')
    seq.append('G92 E0 ; reset extruder origin\n')
    if travel_x is not None and travel_y is not None:
        seq.append(
            f'G1 X{travel_x:.3f} Y{travel_y:.3f} F{xy_feed} '
            '; from homed XY to first live print position; Z stays put\n'
        )
        seq.append('M400 ; wait for XY so pause can interrupt cleanly after this move\n')
    seq.extend(split_gcode_lines(filter_custom_header_no_z(custom_header)))
    seq.append('G11 ; unretract (resume)\n')
    seq.append('; === END RESUME START SEQUENCE ===\n')
    return seq

def find_target_layer_line_by_z_height(layer_changes, target_z):
    """Find the layer change line where the target Z height is reached or exceeded."""
    for layer_info in layer_changes:
        if layer_info['zHeight'] >= target_z:
            return layer_info['lineNumber'] - 1, layer_info['zHeight']  # Convert to 0-based index
    return None, None

def build_resume_header_lines(target_z, actual_z, g28_count, z_moves_count, exec_blocks_count, original_filename, skip_support=False, support_sections_commented=0):
    """Build resume info comment lines (not including slicer header blocks)."""
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
        header_lines.append(f"; First support section skipped after target: {support_sections_commented}\n")
    
    header_lines.extend([
        "; ================================\n",
        "; IMPORTANT: Ensure hotend and bed are at proper temperatures\n",
        "; IMPORTANT: Manually position nozzle near resume point\n",
        "; IMPORTANT: Ensure filament is loaded and primed\n",
        "; IMPORTANT: ALL Z-moves before target layer have been removed\n",
        "; IMPORTANT: Resume does not command Z — bed stays at current height\n",
    ])
    
    if skip_support:
        header_lines.append("; IMPORTANT: First support block after target layer skipped, rest print normally\n")
    else:
        header_lines.append("; IMPORTANT: Content AFTER target layer remains unchanged\n")
    
    header_lines.extend([
        "; ================================\n",
        "\n"
    ])
    
    return header_lines


def add_resume_header(content, target_z, actual_z, g28_count, z_moves_count, exec_blocks_count, original_filename, skip_support=False, support_sections_commented=0):
    """Legacy helper: prepend resume header (prefer build_resume_header_lines + insert_lines_at)."""
    return build_resume_header_lines(
        target_z, actual_z, g28_count, z_moves_count, exec_blocks_count,
        original_filename, skip_support, support_sections_commented
    ) + content

def write_gcode_output(output_filepath, lines):
    """Write processed G-code line-by-line; use temp file + rename for a complete file on disk."""
    tmp_path = output_filepath + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8', buffering=1024 * 1024) as f:
        for line in lines:
            f.write(line)
            if not line.endswith('\n'):
                f.write('\n')
    os.replace(tmp_path, output_filepath)
    os.chmod(output_filepath, 0o644)


def process_gcode_content(content_str, target_z_height, original_filename='unknown.gcode', skip_support=False, custom_header='', output_filepath=None):
    """Process G-code content and write output with statistics.
    
    Args:
        content_str: G-code content as string
        target_z_height: Target Z height to resume from
        original_filename: Original filename
        skip_support: If True, skip printing support sections after target layer
        custom_header: Optional G-code string to place at the very top
        output_filepath: If set, write output directly to this path
    """
    if not content_str:
        raise ValueError("G-code content is empty")
    content = content_str.splitlines()
    
    skip_start = find_skip_start(content)
    
    target_line, actual_z = find_target_layer_line(content, target_z_height)
    if target_line is None:
        if actual_z is not None:
            raise ValueError(
                f"Target Z height {target_z_height}mm exceeds the maximum Z height in the file ({actual_z}mm). "
                f"Please enter a Z height between 0.0mm and {actual_z}mm."
            )
        target_line, max_or_z = find_target_layer_line_legacy(content, target_z_height)
        if target_line is None:
            if max_or_z is None:
                raise ValueError("No Z-axis movements or layer changes found in the file.")
            raise ValueError(
                f"Target Z height {target_z_height}mm exceeds the maximum Z height in the file ({max_or_z}mm). "
                f"Please enter a Z height between 0.0mm and {max_or_z}mm."
            )
        actual_z = max_or_z
    
    # Capture extrusion mode + pressure advance from ORIGINAL gcode before commenting.
    mode_line, pa_line = extract_resume_state(content, target_line)
    
    content, g28_count = remove_g28_commands_before_target(content, target_line)
    content, start_macro_count = comment_out_start_macros_before_target(content, target_line)
    g28_count += start_macro_count
    content, z_moves_count, exec_blocks_count = comment_out_all_z_moves_before_target(content, target_line)
    comment_out_layers(content, skip_start, target_line - 1)
    
    support_sections_commented = 0
    if skip_support:
        content, support_sections_commented = comment_out_support_sections_after_target(content, target_line)
    
    # Keep slicer HEADER/thumbnail blocks at file start for Moonraker/Mainsail metadata.
    # Insert resume comment header before EXECUTABLE_BLOCK_START, not at line 0.
    metadata_end = find_metadata_end_line(content)
    header_lines = build_resume_header_lines(
        target_z_height, actual_z,
        g28_count, z_moves_count, exec_blocks_count, original_filename,
        skip_support, support_sections_commented
    )
    insert_lines_at(content, metadata_end, header_lines)
    if metadata_end <= target_line:
        target_line += len(header_lines)
    
    # Resume entry does not command Z. PRINT_START / homing / slicer Z hops are
    # removed so the bed stays at the physical height you already set.
    # SET_KINEMATIC_POSITION tells Klipper that height without moving.
    region = find_layer_entry_region(content, target_line)
    if region is not None:
        entry_start, entry_end, _hop_x, _hop_y = region
        for k in range(entry_start, entry_end):
            stripped = content[k].strip()
            if stripped and not stripped.startswith(';'):
                content[k] = '; RESUME-REPLACED: ' + content[k]
    
    next_layer = find_next_layer_change(content, target_line)
    strip_z_from_moves(content, target_line, next_layer)
    
    # After skipping support and replacing the slicer hop, go to the first live XY
    # (not the hop onto skipped support). User homes XY; do not SET_KINEMATIC X/Y.
    travel_x, travel_y = find_first_live_xy(content, target_line)
    
    start_sequence = build_resume_start_sequence(
        actual_z, mode_line, pa_line, custom_header, travel_x, travel_y
    )
    insert_lines_at(content, target_line, start_sequence)
    
    commented_lines = target_line - skip_start
    base_name = os.path.splitext(os.path.basename(original_filename))[0]
    output_filename = f"{base_name}_resume_Z{target_z_height}mm.gcode"
    
    if output_filepath is None:
        output_filepath = os.path.join(_GCODES_DIR, output_filename)
    
    out_dir = os.path.dirname(output_filepath)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    write_gcode_output(output_filepath, content)
    
    return {
        'filename': output_filename,
        'filepath': output_filepath,
        'stats': {
            'g28_count': g28_count,
            'z_moves_count': z_moves_count,
            'exec_blocks_count': exec_blocks_count,
            'commented_lines': commented_lines,
            'actual_z': actual_z,
            'target_z': target_z_height,
            'original_filename': original_filename,
            'total_lines': len(content),
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
    print(f"📁 G-codes Directory: {_GCODES_DIR}")
    print(f"🏠 Home Directory: {_HOME_DIR}")
    print(f"📄 HTML File: {os.path.join(_START_AT_LAYER_DIR, 'layer_resume_gui.html')}")
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
  1. Ensure layer_resume_gui.html is in ~/printer_data/config/START_AT_LAYER/ (or same user as Klipper)
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
