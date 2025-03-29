import os
import stat
import platform
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
import datetime
import traceback

# Detect if we're on Render.com
IS_RENDER = os.environ.get('RENDER') == 'true'
# Print environment details for debugging
print(f"Running on: {platform.system()} {platform.release()}")
print(f"Python version: {platform.python_version()}")
print(f"Is Render: {IS_RENDER}")

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

# Define allowed file types
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def clean_filename(filename):
    # Remove common security indicators in filenames
    # This handles variations like (SECURED), [SECURED], [PROTECTED], etc.
    cleaned_name = re.sub(r'\s*[\(\[](?:SECURED|PROTECTED|LOCKED|READONLY)[\)\]]\s*', '', filename, flags=re.IGNORECASE)
    
    # For files like "unlocked_Thuc_hanh_Buoi_2..._Quy_trinh_va_ke_hoach_kiem_thu.pdf (SECURED)"
    # Remove the "unlocked_" prefix if it exists
    if cleaned_name.startswith("unlocked_"):
        cleaned_name = cleaned_name[9:]
        
    return cleaned_name

# Helper function to try password variations
def try_password_variations(pdf_path, password):
    """Try multiple variations of a password on a PDF file."""
    app.logger.info(f"Trying password variations for: {password}")
    variations = [
        password,  # original
        password.strip(),  # without leading/trailing spaces
        f" {password}",  # leading space
        f"{password} ",  # trailing space
        f" {password} ",  # both spaces
    ]
    
    # If numeric, add numeric versions
    if password.isdigit():
        try:
            variations.append(int(password))  # as integer
        except:
            pass
            
    # Add bytes versions
    for var in list(variations):  # Create a copy of the list to avoid modifying during iteration
        if isinstance(var, str):
            try:
                variations.append(var.encode('utf-8'))  # as bytes
            except:
                pass
    
    # Try each variation
    for var in variations:
        try:
            app.logger.info(f"Trying variation: {var} (type: {type(var).__name__})")
            reader = PdfReader(pdf_path)
            if reader.is_encrypted:
                result = reader.decrypt(var)
                app.logger.info(f"Decrypt result: {result}")
                if result > 0 or not reader.is_encrypted:
                    app.logger.info(f"Success with variation: {var}")
                    return reader
        except Exception as e:
            app.logger.warning(f"Failed with variation {var}: {str(e)}")
            
    return None

def unlock_pdf(input_path, output_path, password, file_id=None):
    """
    Unlock a PDF file and save the unlocked version to the specified output path.
    
    Args:
        input_path (str): Path to the input PDF file
        output_path (str): Path where the unlocked PDF should be saved
        password (str): Password to unlock the PDF
        file_id (str, optional): The ID of the file being processed
        
    Returns:
        dict: A dictionary with status and other information
    """
    try:
        app.logger.info(f"Attempting to unlock PDF: {input_path}")
        
        # Try to determine if this is numeric password
        numeric_mode = password.isdigit()
        is_password_int = False
        if numeric_mode:
            try:
                int(password)
                is_password_int = True
                app.logger.info(f"Numeric password detected: {password}")
            except:
                pass
        
        # If we're on Render and this is a numeric password, use specialized handling
        if IS_RENDER and numeric_mode:
            app.logger.info("Using specialized Render numeric password handling")
            reader = try_password_variations(input_path, password)
            
            if reader and not reader.is_encrypted:
                app.logger.info("Successfully opened PDF with variation helper!")
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                    
                with open(output_path, 'wb') as out_file:
                    writer.write(out_file)
                    
                # Check if successful
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    try:
                        verify = PdfReader(output_path)
                        if not verify.is_encrypted:
                            app.logger.info("Successfully verified unlocked PDF!")
                            
                            # Get original filename
                            original_filename = "document.pdf"
                            if file_id:
                                original_filename = protected_files.get(file_id, "document.pdf")
                                
                            # Process filenames
                            cleaned_filename = clean_filename(original_filename)
                            prefixed_filename = f"unlocked_{cleaned_filename}"
                            display_filename = secure_filename(prefixed_filename)
                            
                            # Store in processed files
                            output_filename = os.path.basename(output_path)
                            processed_files[output_filename] = display_filename
                            save_processed_files()
                            
                            # Cleanup if file_id is provided
                            if file_id:
                                if file_id in protected_files:
                                    del protected_files[file_id]
                                    
                                # Remove the input file 
                                if os.path.exists(input_path):
                                    os.remove(input_path)
                            
                            return {
                                'status': 'success',
                                'filename': prefixed_filename,
                                'download_url': f'/download/{output_filename}'
                            }
                    except Exception as verify_error:
                        app.logger.error(f"Verification error: {str(verify_error)}")
        
        # Try PyPDF2 standard method
        try:
            app.logger.info("Trying standard PyPDF2 approach")
            reader = PdfReader(input_path)
            
            # Check if the PDF is password-protected
            if reader.is_encrypted:
                # Try to decrypt the PDF
                decrypt_result = reader.decrypt(password)
                app.logger.info(f"Decrypt result: {decrypt_result}")
                
                if decrypt_result <= 0:  # 0 = wrong password, -1 = no password needed
                    app.logger.info("Failed to decrypt PDF with provided password")
                    return {
                        'status': 'error',
                        'error': 'Incorrect password. Please try again.'
                    }
            else:
                app.logger.info("PDF is not encrypted, creating a copy")
                
            # Write the unlocked PDF to the output path
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
                
            with open(output_path, 'wb') as f:
                writer.write(f)
                
            # Verify the output file is valid and not encrypted
            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                app.logger.error("Output file was not created or is empty")
                return {
                    'status': 'error',
                    'error': 'Failed to create unlocked PDF file'
                }
                
            # Check if the output PDF is really unlocked
            try:
                verify_reader = PdfReader(output_path)
                if verify_reader.is_encrypted:
                    app.logger.error("Output PDF is still encrypted")
                    return {
                        'status': 'error',
                        'error': 'Failed to unlock PDF. Output is still encrypted.'
                    }
            except Exception as verify_error:
                app.logger.error(f"Error verifying output PDF: {str(verify_error)}")
                return {
                    'status': 'error',
                    'error': f'Error verifying output PDF: {str(verify_error)}'
                }
                
            # Get original filename if file_id is provided
            original_filename = "document.pdf"
            if file_id:
                original_filename = protected_files.get(file_id, "document.pdf")
                
            # Process filenames for display
            cleaned_filename = clean_filename(original_filename)
            prefixed_filename = f"unlocked_{cleaned_filename}"
            display_filename = secure_filename(prefixed_filename)
            
            # Store in processed files for later download
            output_filename = os.path.basename(output_path)
            processed_files[output_filename] = display_filename
            save_processed_files()
            
            # Cleanup if file_id is provided
            if file_id:
                if file_id in protected_files:
                    del protected_files[file_id]
                    
                # Remove the input file
                if os.path.exists(input_path):
                    os.remove(input_path)
            
            app.logger.info(f"Successfully unlocked PDF: {original_filename}")
            return {
                'status': 'success',
                'filename': prefixed_filename,
                'download_url': f'/download/{output_filename}'
            }
        except Exception as e:
            app.logger.error(f"Error in standard PyPDF2 approach: {str(e)}")
            # Fall through to next method for Render
        
        # If we're on Render, try one more approach for compatibility
        if IS_RENDER:
            app.logger.info("Attempting Render fallback approach")
            try:
                # Try with alternative approach using file-based password
                password_file = os.path.join(app.config['DATA_FOLDER'], f"pwd_{uuid.uuid4()}.txt")
                with open(password_file, 'w') as f:
                    f.write(password)
                
                # Read the password from file
                with open(password_file, 'r') as f:
                    file_pwd = f.read().strip()
                
                app.logger.info(f"Password read from file: {file_pwd}")
                reader = PdfReader(input_path, password=file_pwd)
                
                if reader.is_encrypted:
                    # Try to decrypt
                    decrypt_result = reader.decrypt(file_pwd)
                    app.logger.info(f"Decrypt result from file-read password: {decrypt_result}")
                    
                    if decrypt_result <= 0:
                        app.logger.info("Failed to decrypt with file-read password")
                        return {
                            'status': 'error',
                            'error': 'Incorrect password. Please try again.'
                        }
                
                # Clean up password file
                if os.path.exists(password_file):
                    os.remove(password_file)
                
                # Write the unlocked PDF
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                    
                with open(output_path, 'wb') as f:
                    writer.write(f)
                
                # Verify output
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    verify_reader = PdfReader(output_path)
                    if not verify_reader.is_encrypted:
                        app.logger.info("Render fallback method succeeded")
                        
                        # Get original filename if file_id is provided
                        original_filename = "document.pdf"
                        if file_id:
                            original_filename = protected_files.get(file_id, "document.pdf")
                            
                        # Process filenames
                        cleaned_filename = clean_filename(original_filename)
                        prefixed_filename = f"unlocked_{cleaned_filename}"
                        display_filename = secure_filename(prefixed_filename)
                        
                        # Store in processed files
                        output_filename = os.path.basename(output_path)
                        processed_files[output_filename] = display_filename
                        save_processed_files()
                        
                        # Cleanup if file_id is provided
                        if file_id:
                            if file_id in protected_files:
                                del protected_files[file_id]
                                
                            # Remove the input file
                            if os.path.exists(input_path):
                                os.remove(input_path)
                        
                        return {
                            'status': 'success',
                            'filename': prefixed_filename,
                            'download_url': f'/download/{output_filename}'
                        }
            except Exception as render_error:
                app.logger.error(f"Render fallback error: {str(render_error)}")
        
        # If we get here, all approaches failed
        return {
            'status': 'error',
            'error': 'Failed to unlock PDF. Please check your password and try again.'
        }
    except Exception as e:
        app.logger.error(f"Error in unlock_pdf: {str(e)}")
        return {
            'status': 'error',
            'error': f'An error occurred: {str(e)}'
        }

# Helper function to clean up temporary files
def _cleanup_temp_files(file_paths):
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                app.logger.debug(f"Removed temporary file: {file_path}")
        except Exception as e:
            app.logger.error(f"Failed to remove temporary file {file_path}: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/unlock', methods=['POST'])
def unlock():
    global protected_files
    
    # Check if any files were uploaded
    if 'files[]' not in request.files:
        return jsonify({'status': 'error', 'message': 'No files were uploaded'}), 400
    
    files = request.files.getlist('files[]')
    results = []
    
    for file in files:
        if file and allowed_file(file.filename):
            # Generate a secure filename to prevent directory traversal attacks
            filename = secure_filename(file.filename)
            
            # Generate a unique ID for this file
            file_id = str(uuid.uuid4())
            
            # Save the file with the unique ID as the filename
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
            file.save(input_path)
            
            # Create the output filename and path
            output_filename = f"unlocked_{file_id}"
            output_path = os.path.join(app.config['PROCESSED_FOLDER'], output_filename)
            
            # Track this file's original name by its ID
            protected_files[file_id] = filename
            
            # Try to unlock the PDF without a password first
            try:
                # First check if the file is a valid PDF
                try:
                    reader = PdfReader(input_path)
                    
                    # Check if the PDF is password-protected
                    if reader.is_encrypted:
                        app.logger.info(f"PDF is password-protected: {filename}")
                        # Return info that password is needed
                        results.append({
                            'file_id': file_id,
                            'filename': file.filename,
                            'status': 'needs_password',
                            'message': 'This PDF is password protected'
                        })
                        continue
                        
                except Exception as e:
                    if "password" in str(e).lower():
                        app.logger.info(f"PDF requires password: {filename}")
                        # Return info that password is needed
                        results.append({
                            'file_id': file_id,
                            'filename': file.filename,
                            'status': 'needs_password',
                            'message': 'This PDF is password protected'
                        })
                        continue
                    else:
                        # Not a password issue, might be a corrupt file
                        app.logger.error(f"Error reading PDF: {str(e)}")
                        results.append({
                            'file_id': file_id,
                            'filename': file.filename,
                            'status': 'error',
                            'message': f'Error: {str(e)}'
                        })
                        
                        # Clean up the file
                        if os.path.exists(input_path):
                            os.remove(input_path)
                        if file_id in protected_files:
                            del protected_files[file_id]
                            
                        continue
                
                # If we get here, the PDF is not password-protected, try to unlock
                unlock_result = unlock_pdf(input_path, output_path, password='', file_id=file_id)
                
                if unlock_result['status'] == 'success':
                    app.logger.info(f"Successfully unlocked PDF: {filename}")
                    # Get the file info
                    display_filename = unlock_result['filename']
                    download_url = unlock_result['download_url']
                    
                    results.append({
                        'filename': display_filename, 
                        'status': 'success',
                        'download_url': download_url
                    })
                else:
                    app.logger.warning(f"Failed to unlock PDF: {filename}")
                    # Failed to unlock, add to results
                    results.append({
                        'file_id': file_id,
                        'filename': file.filename,
                        'status': 'error',
                        'message': unlock_result['error']
                    })
            except Exception as e:
                app.logger.error(f"General error processing PDF: {str(e)}")
                results.append({
                    'filename': file.filename,
                    'status': 'error',
                    'message': f'Error: {str(e)}'
                })
                
                # Clean up the file
                if os.path.exists(input_path):
                    os.remove(input_path)
                if file_id in protected_files:
                    del protected_files[file_id]
        else:
            # Invalid file type
            results.append({
                'filename': file.filename if file else 'Unknown file',
                'status': 'error',
                'message': 'Invalid file type. Only PDF files are accepted.'
            })
    
    return jsonify(results)

@app.route('/unlock-with-password', methods=['POST'])
def unlock_with_password():
    data = request.json
    file_id = data.get('file_id')
    password = data.get('password')
    include_debug = data.get('debug_info', False)
    
    debug_info = {}
    
    if not file_id or not password:
        return jsonify({
            'status': 'error',
            'error': 'Missing file ID or password',
            'debug_info': debug_info if include_debug else None
        })
    
    # Get file path from ID
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
    
    if not os.path.exists(input_path):
        return jsonify({
            'status': 'error',
            'error': 'File not found',
            'debug_info': debug_info if include_debug else None
        })
    
    # Debug information
    if include_debug:
        debug_info['file_id'] = file_id
        debug_info['file_exists'] = os.path.exists(input_path)
        debug_info['file_size'] = os.path.getsize(input_path) if os.path.exists(input_path) else 0
        debug_info['password_type'] = str(type(password))
        debug_info['password_length'] = len(password) if password else 0
        debug_info['is_render'] = IS_RENDER
        debug_info['timestamp'] = datetime.datetime.now().isoformat()
    
    # Create filename for the unlocked file
    output_filename = f"unlocked_{file_id}"
    output_path = os.path.join(app.config['PROCESSED_FOLDER'], output_filename)
    
    # Get the original filename
    original_filename = protected_files.get(file_id, "document.pdf")
    
    # Try to unlock the PDF
    try:
        result = unlock_pdf(input_path, output_path, password)
        
        if include_debug:
            debug_info['unlock_result'] = result
            
        if result.get('status') == 'success':
            # Get the display filename
            display_filename = result.get('filename')
            download_url = result.get('download_url')
            
            return jsonify({
                'status': 'success',
                'filename': display_filename,
                'download_url': download_url,
                'debug_info': debug_info if include_debug else None
            })
        else:
            error_msg = result.get('error', 'Failed to unlock PDF')
            
            return jsonify({
                'status': 'error',
                'error': error_msg,
                'debug_info': debug_info if include_debug else None
            })
    except Exception as e:
        app.logger.error(f"Exception in unlock_with_password: {str(e)}")
        traceback_str = traceback.format_exc()
        
        if include_debug:
            debug_info['exception'] = str(e)
            debug_info['traceback'] = traceback_str
            
        return jsonify({
            'status': 'error',
            'error': f"An error occurred: {str(e)}",
            'debug_info': debug_info if include_debug else None
        })

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