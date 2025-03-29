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

def clean_filename(filename, file_id=None):
    """
    Clean up the filename by removing security indicators and ensuring proper format.
    
    Args:
        filename (str): The original filename
        file_id (str, optional): The unique file ID to use in generated names
        
    Returns:
        str: Cleaned filename without security indicators
    """
    app.logger.info(f"Cleaning filename: {filename}")
    
    # Ensure we're working with a string
    if not filename or not isinstance(filename, str):
        app.logger.info("Invalid filename, using default")
        if file_id:
            # Use file_id to create a unique filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            return f"document_{file_id[:8]}_{timestamp}.pdf"
        else:
            return "document.pdf"
    
    # Store original filename for logging
    original = filename
        
    # Remove common security indicators in filenames
    # This handles variations like (SECURED), [SECURED], [PROTECTED], etc.
    cleaned_name = re.sub(r'\s*[\(\[](?:SECURED|PROTECTED|LOCKED|READONLY)[\)\]]\s*', '', filename, flags=re.IGNORECASE)
    
    # For files like "unlocked_Thuc_hanh_Buoi_2..._Quy_trinh_va_ke_hoach_kiem_thu.pdf (SECURED)"
    # Remove the "unlocked_" prefix if it exists - we'll add it back later consistently
    if cleaned_name.lower().startswith("unlocked_"):
        cleaned_name = cleaned_name[9:]
        
    # Replace consecutive spaces with a single space
    cleaned_name = re.sub(r'\s+', ' ', cleaned_name)
    
    # Remove spaces at the beginning and end
    cleaned_name = cleaned_name.strip()
    
    # Make sure the file has a .pdf extension
    if not cleaned_name.lower().endswith('.pdf'):
        cleaned_name = f"{cleaned_name}.pdf"
    
    # Ensure the name is not empty or just "document.pdf"
    if not cleaned_name or cleaned_name == ".pdf" or cleaned_name.lower() == "document.pdf":
        # Generate a timestamp-based filename instead of using "document.pdf"
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        
        # Extract original filename without extension if possible
        original_without_ext = os.path.splitext(original)[0]
        
        if original_without_ext and original_without_ext.lower() != "document":
            # Use the original name but clean it
            cleaned_name = f"{original_without_ext}_{timestamp}.pdf"
            app.logger.info(f"Using original name with timestamp: {cleaned_name}")
        else:
            # No usable original name, use timestamp with file_id if available
            if file_id:
                cleaned_name = f"document_{file_id[:8]}_{timestamp}.pdf"
            else:
                cleaned_name = f"document_{timestamp}.pdf"
            app.logger.info(f"Generated unique filename: {cleaned_name}")
    
    app.logger.info(f"Filename after cleaning: {cleaned_name}")
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
                            if file_id and file_id in protected_files:
                                original_filename = protected_files.get(file_id, "document.pdf")
                                app.logger.info(f"Retrieved original filename for file_id {file_id}: {original_filename}")
                                
                            # Process filenames
                            cleaned_filename = clean_filename(original_filename, file_id)
                            app.logger.info(f"After cleaning filename: {cleaned_filename}")
                            
                            # Make sure we're not getting an empty or default name
                            if cleaned_filename in ["document.pdf", "", ".pdf"] or cleaned_filename.lower() == "document.pdf":
                                if original_filename and original_filename.lower() != "document.pdf":
                                    # Use the original name but without extension
                                    base_name = os.path.splitext(original_filename)[0]
                                    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                                    cleaned_filename = f"{base_name}_{timestamp}.pdf"
                                    app.logger.info(f"Using modified original filename: {cleaned_filename}")
                                else:
                                    # Generate a completely new name
                                    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                                    cleaned_filename = f"file_{timestamp}.pdf"
                                    app.logger.info(f"Generated unique filename: {cleaned_filename}")
                            
                            # Create the display filename with the 'unlocked_' prefix
                            prefixed_filename = f"unlocked_{cleaned_filename}"
                            display_filename = secure_filename(prefixed_filename)
                            app.logger.info(f"Final display filename: {display_filename}")
                            
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
                                'filename': display_filename,
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
            if file_id and file_id in protected_files:
                original_filename = protected_files.get(file_id, "document.pdf")
                app.logger.info(f"Retrieved original filename for file_id {file_id}: {original_filename}")
            else:
                # If we don't have an original filename, try to create a unique one
                timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                original_filename = f"file_{timestamp}.pdf"
                app.logger.info(f"No original filename found, generated: {original_filename}")
            
            # Process filenames for display
            cleaned_filename = clean_filename(original_filename, file_id)
            app.logger.info(f"After cleaning filename: {cleaned_filename}")
            
            # Make sure we're not getting an empty or default name
            if cleaned_filename in ["document.pdf", "", ".pdf"] or cleaned_filename.lower() == "document.pdf":
                if original_filename and original_filename.lower() != "document.pdf":
                    # Use the original name but without extension
                    base_name = os.path.splitext(original_filename)[0]
                    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    cleaned_filename = f"{base_name}_{timestamp}.pdf"
                    app.logger.info(f"Using modified original filename: {cleaned_filename}")
                else:
                    # Generate a completely new name
                    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    cleaned_filename = f"file_{timestamp}.pdf"
                    app.logger.info(f"Generated unique filename: {cleaned_filename}")
            
            # Create the display filename with the 'unlocked_' prefix
            prefixed_filename = f"unlocked_{cleaned_filename}"
            display_filename = secure_filename(prefixed_filename)
            app.logger.info(f"Final display filename: {display_filename}")
            
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
                'filename': display_filename,
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
                        if file_id and file_id in protected_files:
                            original_filename = protected_files.get(file_id, "document.pdf")
                            app.logger.info(f"Retrieved original filename for file_id {file_id}: {original_filename}")
                        else:
                            # If we don't have an original filename, try to create a unique one
                            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                            original_filename = f"file_{timestamp}.pdf"
                            app.logger.info(f"No original filename found, generated: {original_filename}")
                            
                        # Process filenames
                        cleaned_filename = clean_filename(original_filename, file_id)
                        prefixed_filename = f"unlocked_{cleaned_filename}"
                        display_filename = secure_filename(prefixed_filename)
                        
                        app.logger.info(f"Display filename after cleaning: {display_filename}")
                        
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
                            'filename': display_filename,
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
    
    results = []
    
    # Trường hợp 1: Xử lý files[] - các file mới được tải lên
    if 'files[]' in request.files:
        files = request.files.getlist('files[]')
        
        for file in files:
            if file and allowed_file(file.filename):
                # Generate a secure filename to prevent directory traversal attacks
                original_filename = secure_filename(file.filename)
                
                # Generate a unique ID for this file
                file_id = str(uuid.uuid4())
                
                # Save the file with the unique ID as the filename
                input_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
                file.save(input_path)
                
                # Store original filename for later processing
                protected_files[file_id] = original_filename
                app.logger.info(f"Stored original filename for file_id {file_id}: {original_filename}")
                
                # Create the output filename and path
                output_filename = f"unlocked_{file_id}"
                output_path = os.path.join(app.config['PROCESSED_FOLDER'], output_filename)
                
                # Try to unlock the PDF
                try:
                    # First check if the file is a valid PDF
                    try:
                        reader = PdfReader(input_path)
                        
                        # Check if the PDF is password-protected
                        if reader.is_encrypted:
                            # Try with empty password first
                            decrypt_result = reader.decrypt('')
                            
                            # If decrypt_result > 0, file can be opened without password
                            if decrypt_result <= 0:
                                app.logger.info(f"PDF requires password: {original_filename}")
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
                            app.logger.info(f"PDF requires password: {original_filename}")
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
                        app.logger.info(f"Successfully unlocked PDF: {original_filename}")
                        # Get the file info
                        display_filename = unlock_result['filename']
                        download_url = unlock_result['download_url']
                        
                        results.append({
                            'filename': display_filename, 
                            'status': 'success',
                            'download_url': download_url
                        })
                    else:
                        app.logger.warning(f"Failed to unlock PDF: {original_filename}")
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
    
    # Trường hợp 2: Xử lý file_ids[] - các file đã được tải lên trước đó
    if 'file_ids[]' in request.form:
        file_ids = request.form.getlist('file_ids[]')
        
        for file_id in file_ids:
            # Get the input path
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
            
            if not os.path.exists(input_path):
                results.append({
                    'file_id': file_id,
                    'status': 'error',
                    'message': 'File not found on server'
                })
                continue
                
            # Get original filename
            original_filename = protected_files.get(file_id, "document.pdf")
            app.logger.info(f"Processing existing file with ID {file_id}, original name: {original_filename}")
            
            # Create output path
            output_filename = f"unlocked_{file_id}"
            output_path = os.path.join(app.config['PROCESSED_FOLDER'], output_filename)
            
            # Try to unlock the file
            try:
                unlock_result = unlock_pdf(input_path, output_path, password='', file_id=file_id)
                
                if unlock_result['status'] == 'success':
                    app.logger.info(f"Successfully unlocked PDF with ID: {file_id}")
                    # Get the file info
                    display_filename = unlock_result['filename']
                    download_url = unlock_result['download_url']
                    
                    results.append({
                        'file_id': file_id,
                        'filename': display_filename, 
                        'status': 'success',
                        'download_url': download_url
                    })
                else:
                    app.logger.warning(f"Failed to unlock PDF with ID: {file_id}")
                    # Check if the error message indicates a password is needed
                    if 'password' in unlock_result['error'].lower():
                        results.append({
                            'file_id': file_id,
                            'filename': original_filename,
                            'status': 'needs_password',
                            'message': 'This PDF is password protected'
                        })
                    else:
                        # Failed to unlock, add to results
                        results.append({
                            'file_id': file_id,
                            'filename': original_filename,
                            'status': 'error',
                            'message': unlock_result['error']
                        })
            except Exception as e:
                app.logger.error(f"General error processing PDF with ID {file_id}: {str(e)}")
                results.append({
                    'file_id': file_id,
                    'status': 'error',
                    'message': f'Error: {str(e)}'
                })
    
    if not results:
        return jsonify({'status': 'error', 'message': 'No files were processed'}), 400
    
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
    original_filename = protected_files.get(file_id, f"document_{file_id[:8]}.pdf")
    
    app.logger.info(f"Original filename from protected_files for file_id {file_id}: {original_filename}")
    
    # Try to unlock the PDF
    try:
        result = unlock_pdf(input_path, output_path, password, file_id=file_id)
        
        if include_debug:
            debug_info['unlock_result'] = result
            
        if result.get('status') == 'success':
            # Get the display filename
            display_filename = result.get('filename')
            download_url = result.get('download_url')
            
            app.logger.info(f"Successfully unlocked with password, display filename: {display_filename}")
            
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
        
        # Extract the file_id from the filename if possible
        file_id = None
        if filename.startswith("unlocked_"):
            file_id = filename[9:]  # Extract the UUID part
        
        app.logger.info(f"Download requested for: {filename}, extracted file_id: {file_id}")
        
        # Get the display filename from our tracking dictionary
        display_filename = processed_files.get(filename, filename)
        app.logger.info(f"Display filename from processed_files: {display_filename}")
        
        # Get just the base filename without the 'unlocked_' prefix if it exists
        if display_filename.startswith("unlocked_"):
            base_filename = display_filename[9:]
        else:
            base_filename = display_filename
            
        # Make sure we're not using a generic "document.pdf" filename
        if base_filename in ["document.pdf", ".pdf", ""] or base_filename.startswith("document_"):
            # Try to get the original filename from protected_files if file_id is available
            if file_id and file_id in protected_files:
                original_name = protected_files.get(file_id)
                app.logger.info(f"Found original filename in protected_files: {original_name}")
                
                # Clean up original name
                if original_name:
                    base_filename = clean_filename(original_name, file_id)
                    app.logger.info(f"Using original filename for download: {base_filename}")
            
            # If we still don't have a good name, generate a unique one
            if base_filename in ["document.pdf", ".pdf", ""] or base_filename.startswith("document_"):
                # Generate a more descriptive filename with timestamp and file_id
                timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                if file_id:
                    base_filename = f"file_{file_id[:8]}_{timestamp}.pdf"
                else:
                    base_filename = f"file_{timestamp}.pdf"
                app.logger.info(f"Generated new base filename: {base_filename}")
        
        # Create the final download filename with the 'unlocked_' prefix
        final_filename = f"unlocked_{base_filename}"
        app.logger.info(f"Final download filename: {final_filename}")
        
        # Create the response with the properly named file
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=final_filename
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
        
        # Keep track of filenames used in the ZIP to prevent duplicates
        used_filenames = set()
        
        # Create a ZIP file in memory
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_url in file_urls:
                # Extract the filename from the URL
                filename = file_url.split('/')[-1]
                file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
                
                if os.path.exists(file_path):
                    # Extract file_id if possible
                    file_id = None
                    if filename.startswith("unlocked_"):
                        file_id = filename[9:]
                    
                    # Get the display filename for the ZIP archive
                    display_filename = processed_files.get(filename, filename)
                    app.logger.info(f"ZIP: Original display filename for {filename}: {display_filename}")
                    
                    # Get just the base filename without the 'unlocked_' prefix if it exists
                    if display_filename.startswith("unlocked_"):
                        base_filename = display_filename[9:]
                    else:
                        base_filename = display_filename
                    
                    # Try to get original filename from protected_files
                    if file_id and file_id in protected_files:
                        original_name = protected_files.get(file_id)
                        if original_name:
                            base_filename = clean_filename(original_name, file_id)
                            app.logger.info(f"ZIP: Using original filename: {base_filename}")
                    
                    # Make sure we're not using a generic "document.pdf" filename
                    if base_filename in ["document.pdf", ".pdf", ""] or base_filename.startswith("document_"):
                        # Generate a unique name based on file_id if available
                        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                        if file_id:
                            base_filename = f"file_{file_id[:8]}_{timestamp}.pdf"
                        else:
                            base_filename = f"file_{timestamp}_{len(used_filenames)}.pdf"
                        app.logger.info(f"ZIP: Generated new base filename: {base_filename}")
                    
                    # Create the final archive filename with the 'unlocked_' prefix
                    final_filename = f"unlocked_{base_filename}"
                    
                    # Check if this name is already used in the ZIP and make it unique if needed
                    if final_filename in used_filenames:
                        name_without_ext = os.path.splitext(final_filename)[0]
                        ext = os.path.splitext(final_filename)[1]
                        counter = 1
                        while final_filename in used_filenames:
                            final_filename = f"{name_without_ext}_{counter}{ext}"
                            counter += 1
                    
                    # Record this filename as used
                    used_filenames.add(final_filename)
                    
                    app.logger.info(f"ZIP: Final archive filename: {final_filename}")
                    
                    # Add the file to the ZIP archive with the proper name
                    zf.write(file_path, arcname=final_filename)
        
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
        total_processed = 0
        total_uploads = 0
        
        # Cleanup upload folder
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path)) > 3600:
                try:
                    os.remove(file_path)
                    count += 1
                    total_uploads += 1
                    app.logger.info(f"Removed old upload file: {file_path}")
                    
                    # Remove from protected_files if it's there
                    if filename in protected_files:
                        del protected_files[filename]
                except Exception as e:
                    app.logger.error(f"Error removing file {file_path}: {str(e)}")
                
        # Cleanup processed folder
        for filename in os.listdir(app.config['PROCESSED_FOLDER']):
            file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
            if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path)) > 3600:
                try:
                    os.remove(file_path)
                    count += 1
                    total_processed += 1
                    app.logger.info(f"Removed old processed file: {file_path}")
                    
                    # Remove from tracking dictionary
                    if filename in processed_files:
                        del processed_files[filename]
                except Exception as e:
                    app.logger.error(f"Error removing file {file_path}: {str(e)}")
                
        # Save the updated processed files dictionary
        save_processed_files()
                
        return jsonify({
            'status': 'success',
            'message': f'Removed {count} old files ({total_uploads} uploads, {total_processed} processed)'
        }), 200
    except Exception as e:
        app.logger.error(f"Cleanup error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Add a background thread for automatic cleanup
def setup_periodic_cleanup():
    """Set up a background thread to run cleanup periodically"""
    import threading
    
    def cleanup_thread():
        while True:
            try:
                app.logger.info("Running scheduled cleanup")
                # Remove files older than 1 hour
                current_time = time.time()
                cleaned_count = 0
                
                # Clean up upload folder
                for filename in os.listdir(app.config['UPLOAD_FOLDER']):
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path)) > 3600:
                        try:
                            os.remove(file_path)
                            cleaned_count += 1
                            
                            # Remove from protected_files if it's there
                            if filename in protected_files:
                                del protected_files[filename]
                        except:
                            pass
                
                # Clean up processed folder
                for filename in os.listdir(app.config['PROCESSED_FOLDER']):
                    file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
                    if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path)) > 3600:
                        try:
                            os.remove(file_path)
                            cleaned_count += 1
                            
                            # Remove from tracking dictionary
                            if filename in processed_files:
                                del processed_files[filename]
                        except:
                            pass
                
                # Save the updated processed files dictionary
                if cleaned_count > 0:
                    try:
                        save_processed_files()
                        app.logger.info(f"Scheduled cleanup removed {cleaned_count} files")
                    except:
                        pass
                        
            except Exception as e:
                app.logger.error(f"Error in cleanup thread: {str(e)}")
                
            # Sleep for 15 minutes
            time.sleep(15 * 60)
    
    # Start the cleanup thread
    thread = threading.Thread(target=cleanup_thread)
    thread.daemon = True  # Thread will exit when main thread exits
    thread.start()
    app.logger.info("Started background cleanup thread")

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

@app.route('/check-password', methods=['POST'])
def check_password():
    # Check if any files were uploaded
    if 'files[]' not in request.files:
        return jsonify({'status': 'error', 'message': 'No files were uploaded'}), 400
    
    file = request.files.getlist('files[]')[0]  # Lấy file đầu tiên
    
    if file and allowed_file(file.filename):
        # Generate a unique ID for this file
        file_id = str(uuid.uuid4())
        
        # Save the file temporarily
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
        file.save(input_path)
        
        # Store original filename for later use
        original_filename = secure_filename(file.filename)
        app.logger.info(f"Original filename for file_id {file_id}: {original_filename}")
        
        # Check if the file is password-protected
        try:
            reader = PdfReader(input_path)
            
            # Check if the PDF is encrypted
            if reader.is_encrypted:
                # Try to open with an empty password
                decrypt_result = reader.decrypt('')
                
                # If decrypt_result > 0, it means the file is only owner-password protected
                # and can be accessed without a user password (decrypt_result = 1 or 2)
                if decrypt_result > 0:
                    app.logger.info(f"File is encrypted but can be opened without password: {file.filename}")
                    
                    # We can process this file without password
                    protected_files[file_id] = original_filename
                    return jsonify({
                        'needs_password': False,
                        'file_id': file_id,
                        'filename': file.filename,
                        'status': 'success'
                    })
                else:
                    # Store original filename for later use - this file needs a password
                    protected_files[file_id] = original_filename
                    
                    return jsonify({
                        'needs_password': True,
                        'file_id': file_id,
                        'filename': file.filename
                    })
            else:
                # Not encrypted at all
                protected_files[file_id] = original_filename
                return jsonify({
                    'needs_password': False,
                    'file_id': file_id,
                    'filename': file.filename,
                    'status': 'success'
                })
        except Exception as e:
            # Check if the error is related to password protection
            if "password" in str(e).lower():
                # Store original filename for later use
                protected_files[file_id] = original_filename
                
                # If it specifically mentions incorrect password, it definitely needs one
                return jsonify({
                    'needs_password': True,
                    'file_id': file_id,
                    'filename': file.filename
                })
            else:
                # Some other error occurred
                if os.path.exists(input_path):
                    os.remove(input_path)
                
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
    else:
        return jsonify({
            'status': 'error', 
            'message': 'Invalid file type'
        })

@app.route('/session-status', methods=['GET'])
def session_status():
    """
    Check if there are any files in the session that need to be processed
    This helps with determining if we need to clear data when a tab is closed
    """
    try:
        # Count files in uploads and processed folders
        upload_files = os.listdir(app.config['UPLOAD_FOLDER'])
        processed_files_list = os.listdir(app.config['PROCESSED_FOLDER'])
        
        upload_count = len(upload_files)
        processed_count = len(processed_files_list)
        
        # Check if we have data in memory
        protected_count = len(protected_files)
        processed_dict_count = len(processed_files)
        
        return jsonify({
            'status': 'success',
            'has_data': upload_count > 0 or processed_count > 0 or protected_count > 0 or processed_dict_count > 0,
            'counts': {
                'uploads': upload_count,
                'processed': processed_count,
                'protected_files': protected_count,
                'processed_files_dict': processed_dict_count
            }
        }), 200
    except Exception as e:
        app.logger.error(f"Session status error: {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

if __name__ == "__main__":
    # Start the periodic cleanup thread
    setup_periodic_cleanup()
    
    # Use PORT from environment if available (for Render.com and other hosting services)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False) 