import os
import stat
from flask import Flask, request, render_template, send_file, jsonify
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader, PdfWriter
import re
import uuid
import shutil
import time
import zipfile
import io
import json
from urllib.parse import unquote
import base64

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads and processed folders in the current directory
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
PROCESSED_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed')
DATA_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

# Ensure all directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(DATA_FOLDER, exist_ok=True)

# Fix permissions for folders
def ensure_folder_permissions():
    try:
        # Make sure data folders have write permission
        for folder in [UPLOAD_FOLDER, PROCESSED_FOLDER, DATA_FOLDER]:
            # Get current permission
            current_mode = os.stat(folder).st_mode
            
            # Add write permission if not present (user and group)
            if not (current_mode & stat.S_IWUSR) or not (current_mode & stat.S_IWGRP):
                new_mode = current_mode | stat.S_IWUSR | stat.S_IWGRP
                os.chmod(folder, new_mode)
                app.logger.info(f"Fixed permissions for {folder}")
                
        # Test write permission by creating and removing a test file
        for folder in [UPLOAD_FOLDER, PROCESSED_FOLDER, DATA_FOLDER]:
            test_file = os.path.join(folder, f'test_write_{uuid.uuid4()}.tmp')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            app.logger.info(f"Write test successful for {folder}")
            
    except Exception as e:
        app.logger.error(f"Failed to fix permissions: {str(e)}")

# Run permission check at startup
ensure_folder_permissions()

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROCESSED_FOLDER'] = PROCESSED_FOLDER
app.config['DATA_FOLDER'] = DATA_FOLDER

# Path to store processed files information
PROCESSED_FILES_DB = os.path.join(DATA_FOLDER, 'processed_files.json')

# Dictionary to track processed files
processed_files = {}

# Dictionary to track password-protected files
protected_files = {}

# Load processed files data from file if it exists
def load_processed_files():
    global processed_files
    if os.path.exists(PROCESSED_FILES_DB):
        try:
            with open(PROCESSED_FILES_DB, 'r') as f:
                processed_files = json.load(f)
        except Exception as e:
            app.logger.error(f"Error loading processed files data: {str(e)}")
            processed_files = {}

# Save processed files data to file
def save_processed_files():
    try:
        # First write to a temporary file
        temp_file = os.path.join(app.config['DATA_FOLDER'], f'temp_{uuid.uuid4()}.json')
        
        with open(temp_file, 'w') as f:
            json.dump(processed_files, f)
            
        # Make sure the file was written successfully
        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            # Then rename it to the actual file (atomic operation)
            shutil.move(temp_file, PROCESSED_FILES_DB)
        else:
            raise Exception("Failed to write data to temporary file")
            
    except Exception as e:
        # If anything fails, try a direct write as fallback
        try:
            app.logger.error(f"Error in primary save method: {str(e)}, trying direct write")
            with open(PROCESSED_FILES_DB, 'w') as f:
                json.dump(processed_files, f)
        except Exception as e2:
            app.logger.error(f"Error saving processed files data: {str(e2)}")
            raise

# Load processed files on startup
load_processed_files()

def clean_filename(filename):
    # Remove common security indicators in filenames
    # This handles variations like (SECURED), [SECURED], [PROTECTED], etc.
    cleaned_name = re.sub(r'\s*[\(\[](?:SECURED|PROTECTED|LOCKED|READONLY)[\)\]]\s*', '', filename, flags=re.IGNORECASE)
    
    # For files like "unlocked_Thuc_hanh_Buoi_2..._Quy_trinh_va_ke_hoach_kiem_thu.pdf (SECURED)"
    # Remove the "unlocked_" prefix if it exists
    if cleaned_name.startswith("unlocked_"):
        cleaned_name = cleaned_name[9:]
        
    return cleaned_name

def unlock_pdf(input_path, output_path, password=None):
    try:
        # First attempt to open PDF with password if provided
        if password:
            try:
                # Try opening with PdfReader first method
                reader = PdfReader(input_path)
                if reader.is_encrypted:
                    # Decrypt using the first method
                    success = reader.decrypt(password)
                    
                    # If not successful, try alternate approach
                    if success != 1:
                        # Log attempt
                        app.logger.info(f"First decrypt attempt failed, trying alternate method")
                        
                        # Try direct construction with password
                        try:
                            reader = PdfReader(input_path, password=password)
                            # Check if still encrypted after providing password
                            if reader.is_encrypted:
                                app.logger.error("PDF still encrypted after providing password")
                                return {"status": "error", "message": "Incorrect password"}
                        except Exception as pw_error:
                            app.logger.error(f"Second decrypt attempt failed: {str(pw_error)}")
                            return {"status": "error", "message": "Incorrect password"}
            except Exception as e:
                app.logger.error(f"Error opening PDF: {str(e)}")
                return {"status": "error", "message": f"Error opening PDF: {str(e)}"}
        else:
            # Try to open without password
            try:
                reader = PdfReader(input_path)
                # Check if document is encrypted - needs password
                if reader.is_encrypted:
                    return {"status": "needs_password", "message": "This PDF is password protected"}
            except Exception as e:
                if "password" in str(e).lower():
                    return {"status": "needs_password", "message": "This PDF is password protected"}
                else:
                    return {"status": "error", "message": str(e)}
                    
        # Create a writer for the output file
        writer = PdfWriter()
        
        # Add each page to the writer
        for page in reader.pages:
            writer.add_page(page)
            
        # Write the output PDF without encryption
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
            
        # Verify output file was created and has content
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return {"status": "success", "message": "PDF unlocked successfully"}
        else:
            return {"status": "error", "message": "Failed to create output file"}
            
    except Exception as e:
        app.logger.error(f"Error unlocking PDF: {str(e)}")
        return {"status": "error", "message": f"File has not been decrypted: {str(e)}"}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/unlock', methods=['POST'])
def unlock():
    if 'files[]' not in request.files:
        return jsonify({'error': 'No files uploaded'}), 400
    
    # Get password if provided
    password = request.form.get('password')
    
    files = request.files.getlist('files[]')
    results = []
    
    for file in files:
        if file.filename == '':
            continue
            
        if not file.filename.lower().endswith('.pdf'):
            results.append({
                'filename': file.filename,
                'status': 'error',
                'message': 'Not a PDF file'
            })
            continue
            
        try:
            # Clean the filename by removing "(SECURED)" text
            cleaned_filename = clean_filename(file.filename)
            
            # Add "unlocked_" prefix to the cleaned filename
            prefixed_filename = f"unlocked_{cleaned_filename}"
            
            # Generate unique IDs for input and output files
            input_id = str(uuid.uuid4())
            output_id = str(uuid.uuid4())
            
            # Use the unique IDs for filenames to avoid conflicts
            input_filename = f"{input_id}.pdf"
            output_filename = f"{output_id}.pdf"
            
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], input_filename)
            output_path = os.path.join(app.config['PROCESSED_FOLDER'], output_filename)
            
            # Save original file
            file.save(input_path)
            
            # Attempt to unlock the PDF
            unlock_result = unlock_pdf(input_path, output_path, password)
            
            if unlock_result["status"] == "success":
                # Store the mapping between output ID and prefixed filename for download
                display_filename = secure_filename(prefixed_filename)
                processed_files[output_filename] = display_filename
                save_processed_files()  # Save the updated processed files dictionary
                
                results.append({
                    'filename': prefixed_filename,
                    'status': 'success',
                    'download_url': f'/download/{output_filename}'
                })
            elif unlock_result["status"] == "needs_password":
                # Store original filename for later use
                global protected_files
                protected_files[input_filename] = file.filename
                
                # Return a status indicating password is needed
                results.append({
                    'filename': file.filename,
                    'status': 'needs_password',
                    'message': 'This PDF is password protected',
                    'file_id': input_filename  # Send back the ID to reference this file
                })
            else:
                # Some other error occurred
                results.append({
                    'filename': file.filename,
                    'status': 'error',
                    'message': unlock_result["message"]
                })
            
            # Cleanup input file if it's not password protected
            # If password protected, we'll keep it for when they provide a password
            if unlock_result["status"] != "needs_password" and os.path.exists(input_path):
                os.remove(input_path)
                
        except Exception as e:
            results.append({
                'filename': file.filename,
                'status': 'error',
                'message': str(e)
            })
    
    return jsonify(results)

@app.route('/unlock-with-password', methods=['POST'])
def unlock_with_password():
    global protected_files
    
    data = request.json
    if not data or 'file_id' not in data or 'password' not in data:
        return jsonify({'error': 'Missing file_id or password'}), 400
    
    file_id = data['file_id']
    password = data['password']
    
    try:
        # Construct the paths
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
        
        if not os.path.exists(input_path):
            return jsonify({
                'status': 'error',
                'message': 'File not found or expired'
            }), 404
            
        # Generate a unique ID for the output file
        output_id = str(uuid.uuid4())
        output_filename = f"{output_id}.pdf"
        output_path = os.path.join(app.config['PROCESSED_FOLDER'], output_filename)
        
        # Try to unlock the PDF with the provided password
        unlock_result = unlock_pdf(input_path, output_path, password)
        
        if unlock_result["status"] == "success":
            # Get the original filename from our protected_files dictionary
            original_filename = protected_files.get(file_id, "document.pdf")
            
            # Clean and prefix the filename
            cleaned_filename = clean_filename(original_filename)
            prefixed_filename = f"unlocked_{cleaned_filename}"
            
            # Store the mapping between output ID and prefixed filename for download
            display_filename = secure_filename(prefixed_filename)
            processed_files[output_filename] = display_filename
            save_processed_files()  # Save the updated processed files dictionary
            
            # Cleanup the input file and remove from tracking
            if os.path.exists(input_path):
                os.remove(input_path)
            
            # Remove from protected files tracking
            if file_id in protected_files:
                del protected_files[file_id]
                
            return jsonify({
                'status': 'success',
                'filename': prefixed_filename,
                'download_url': f'/download/{output_filename}'
            })
        else:
            return jsonify({
                'status': unlock_result["status"],
                'message': unlock_result["message"]
            })
            
    except Exception as e:
        app.logger.error(f"Error unlocking with password: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/download/<filename>')
def download(filename):
    try:
        file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': f'File not found: {file_path}'}), 404
        
        # Get the display filename from our tracking dictionary or use the filename as is
        display_filename = processed_files.get(filename, filename)
        
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=display_filename
        )
        
        return response
    except Exception as e:
        app.logger.error(f"Download error: {str(e)}")
        return jsonify({'error': str(e)}), 404

@app.route('/download-all', methods=['POST'])
def download_all():
    try:
        # Get the list of file URLs from the request
        data = request.json
        if not data or 'files' not in data or not data['files']:
            return jsonify({'error': 'No files specified'}), 400
        
        file_urls = data['files']
        memory_file = io.BytesIO()
        
        # Create a ZIP file in memory
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_url in file_urls:
                # Extract the filename from the URL
                filename = file_url.split('/')[-1]
                file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
                
                if os.path.exists(file_path):
                    # Get the display filename for the ZIP archive
                    display_filename = processed_files.get(filename, filename)
                    
                    # Make sure the display filename has the "unlocked_" prefix
                    if not display_filename.startswith("unlocked_"):
                        display_filename = f"unlocked_{display_filename}"
                    
                    # Add the file to the ZIP archive
                    zf.write(file_path, arcname=display_filename)
        
        # Create a unique ID for the ZIP file
        zip_id = str(uuid.uuid4())
        zip_filename = f"unlocked_pdfs_{zip_id}.zip"
        zip_path = os.path.join(app.config['PROCESSED_FOLDER'], zip_filename)
        
        # Save the ZIP file
        memory_file.seek(0)
        with open(zip_path, 'wb') as f:
            f.write(memory_file.getvalue())
        
        return jsonify({'status': 'success', 'download_url': f'/download-zip/{zip_filename}'})
    
    except Exception as e:
        app.logger.error(f"Create ZIP error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/download-zip/<filename>')
def download_zip(filename):
    try:
        zip_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
        
        if not os.path.exists(zip_path):
            return jsonify({'error': f'ZIP file not found: {zip_path}'}), 404
        
        # Return the ZIP file
        response = send_file(
            zip_path,
            as_attachment=True,
            download_name="unlocked_pdfs.zip"
        )
        
        return response
    except Exception as e:
        app.logger.error(f"Download ZIP error: {str(e)}")
        return jsonify({'error': str(e)}), 404

@app.route('/clear-processed', methods=['POST'])
def clear_processed():
    try:
        # Get list of files to remove (optional)
        data = request.json
        file_ids = data.get('file_ids', []) if data else []
        
        removed_files = []
        errors = []
        
        if file_ids:
            # Only clear specific files
            for file_id in file_ids:
                try:
                    if file_id in processed_files:
                        # Remove from tracking dictionary
                        display_name = processed_files.pop(file_id, file_id)
                        
                        # Remove the actual file if it exists
                        file_path = os.path.join(app.config['PROCESSED_FOLDER'], file_id)
                        if os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                                removed_files.append(file_id)
                            except Exception as e:
                                errors.append(f"Could not delete {file_id}: {str(e)}")
                        else:
                            # File doesn't exist but we removed it from tracking
                            removed_files.append(file_id)
                except Exception as file_error:
                    errors.append(f"Error processing {file_id}: {str(file_error)}")
        else:
            # Get a copy of keys to avoid modification during iteration
            file_ids_to_remove = list(processed_files.keys())
            
            # Clear all processed files
            for file_id in file_ids_to_remove:
                try:
                    # Remove the actual file if it exists
                    file_path = os.path.join(app.config['PROCESSED_FOLDER'], file_id)
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            removed_files.append(file_id)
                        except Exception as e:
                            errors.append(f"Could not delete {file_id}: {str(e)}")
                    else:
                        # File doesn't exist but we'll remove it from tracking
                        removed_files.append(file_id)
                except Exception as file_error:
                    errors.append(f"Error processing {file_id}: {str(file_error)}")
            
            # Clear the dictionary completely
            processed_files.clear()
        
        # Save the updated processed files dictionary
        try:
            save_processed_files()
        except Exception as save_error:
            errors.append(f"Error saving processed files data: {str(save_error)}")
        
        if errors:
            app.logger.error(f"Clear processed errors: {', '.join(errors)}")
            return jsonify({
                'status': 'partial_success',
                'message': f'Removed {len(removed_files)} files with {len(errors)} errors',
                'errors': errors
            }), 200
        
        return jsonify({
            'status': 'success',
            'message': f'Successfully removed {len(removed_files)} files'
        })
    except Exception as e:
        app.logger.error(f"Clear processed error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Cleanup function to periodically remove old files
@app.route('/cleanup', methods=['GET'])
def cleanup():
    try:
        # Remove files older than 1 hour (optional)
        current_time = time.time()
        count = 0
        
        # Cleanup upload folder
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path)) > 3600:
                os.remove(file_path)
                count += 1
                
        # Cleanup processed folder
        for filename in os.listdir(app.config['PROCESSED_FOLDER']):
            file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
            if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path)) > 3600:
                os.remove(file_path)
                # Remove from tracking dictionary
                if filename in processed_files:
                    del processed_files[filename]
                count += 1
                
        # Save the updated processed files dictionary
        save_processed_files()
                
        return jsonify({'message': f'Removed {count} old files'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get-processed-files', methods=['GET'])
def get_processed_files():
    try:
        # Create a list of files with their display names and download URLs
        files_list = []
        
        for filename, display_name in processed_files.items():
            # Check if the file still exists on the server
            file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
            if os.path.exists(file_path):
                files_list.append({
                    'filename': filename,
                    'display_name': display_name,
                    'download_url': f'/download/{filename}'
                })
            else:
                # File no longer exists, remove from tracking dictionary
                del processed_files[filename]
        
        return jsonify({'files': files_list})
    except Exception as e:
        app.logger.error(f"Get processed files error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Add emergency reset endpoint
@app.route('/emergency-reset', methods=['POST'])
def emergency_reset():
    try:
        # Clear the processed files dictionary
        processed_files.clear()
        
        # Try to delete the JSON file
        if os.path.exists(PROCESSED_FILES_DB):
            try:
                os.remove(PROCESSED_FILES_DB)
            except:
                pass
                
        # Re-create folders with proper permissions
        for folder in [UPLOAD_FOLDER, PROCESSED_FOLDER, DATA_FOLDER]:
            # Try to delete all files in the folder
            try:
                for filename in os.listdir(folder):
                    file_path = os.path.join(folder, filename)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                        except:
                            pass
            except:
                pass
                
        # Ensure folders exist with proper permissions
        ensure_folder_permissions()
        
        # Create empty processed files file
        try:
            with open(PROCESSED_FILES_DB, 'w') as f:
                json.dump({}, f)
        except:
            pass
            
        return jsonify({
            'status': 'success',
            'message': 'Emergency reset completed. Please refresh the page.'
        })
    except Exception as e:
        app.logger.error(f"Emergency reset error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    # Use PORT from environment if available (for Render.com and other hosting services)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False) 