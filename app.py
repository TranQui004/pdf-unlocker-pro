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
    # Define temporary files that might be created
    temp_files = [
        output_path + ".method2",
        output_path + ".method3",
        output_path + ".method4"
    ]
    
    try:
        # Track our attempted methods
        tried_methods = []
        
        # APPROACH 1: Direct decryption with PyPDF2
        tried_methods.append("direct_decryption")
        
        # First attempt to open PDF with password if provided
        if password:
            try:
                # Try different password encodings if necessary (production environments might have encoding issues)
                try:
                    # First try with the password as provided
                    app.logger.info(f"Attempting to decrypt with password as provided")
                    reader = PdfReader(input_path, password=password)
                    if reader.is_encrypted:
                        reader.decrypt(password)
                except Exception as e1:
                    app.logger.warning(f"First password attempt failed: {str(e1)}")
                    # Try encoding password as UTF-8 explicitly
                    try:
                        app.logger.info(f"Attempting with UTF-8 encoded password")
                        pwd_utf8 = password.encode('utf-8').decode('utf-8')
                        reader = PdfReader(input_path, password=pwd_utf8)
                        if reader.is_encrypted:
                            reader.decrypt(pwd_utf8)
                    except Exception as e2:
                        app.logger.warning(f"UTF-8 password attempt failed: {str(e2)}")
                        # Try with ISO-8859-1 encoding
                        try:
                            app.logger.info(f"Attempting with ISO-8859-1 encoded password")
                            pwd_latin = password.encode('iso-8859-1').decode('iso-8859-1')
                            reader = PdfReader(input_path, password=pwd_latin)
                            if reader.is_encrypted:
                                reader.decrypt(pwd_latin)
                        except Exception as e3:
                            # If all attempts fail, raise the original error
                            app.logger.error(f"All password encoding attempts failed")
                            raise e1
                
                # If we get here, one of the attempts succeeded
                app.logger.info("Successfully opened PDF with password")
            except Exception as e:
                app.logger.error(f"Password error: {str(e)}")
                if "password" in str(e).lower():
                    return {"status": "error", "message": "Incorrect password"}
                else:
                    return {"status": "error", "message": str(e)}
        else:
            # Try to open without password
            try:
                reader = PdfReader(input_path)
                # Check if file is encrypted
                if reader.is_encrypted:
                    return {"status": "needs_password", "message": "This PDF is password protected"}
            except Exception as e:
                if "password" in str(e).lower():
                    return {"status": "needs_password", "message": "This PDF is password protected"}
                else:
                    return {"status": "error", "message": str(e)}
        
        # Verify the PDF is not still encrypted
        if reader.is_encrypted:
            app.logger.warning("PDF is still encrypted after decrypt attempt with the first approach")
            # Continue to next approach instead of returning error
        else:
            # Create a writer for the output file
            writer = PdfWriter()
            
            # Add each page to the writer
            for page in reader.pages:
                writer.add_page(page)
            
            # Write the output PDF without encryption
            with open(output_path, 'wb') as output_file:
                writer.write(output_file)
                
            # Verify the output file is not encrypted
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                try:
                    verification_reader = PdfReader(output_path)
                    if not verification_reader.is_encrypted:
                        # Success with method 1, clean up and return
                        _cleanup_temp_files(temp_files)
                        return {"status": "success", "message": "PDF unlocked successfully"}
                except Exception:
                    pass  # If verification fails, try next method
            
        # APPROACH 2: Create a new PDF with the content, avoiding encryption metadata
        tried_methods.append("new_pdf_creation")
        app.logger.info("Trying second approach: Creating new PDF without encryption metadata")
        
        try:
            # Re-open the original PDF with password
            if password:
                original_reader = PdfReader(input_path, password=password)
                original_reader.decrypt(password)
            else:
                original_reader = reader
                
            # Create a brand new writer
            new_writer = PdfWriter()
            
            # Copy each page and its contents to ensure no encryption persists
            for page_num in range(len(original_reader.pages)):
                page = original_reader.pages[page_num]
                new_writer.add_page(page)
            
            # Write to a different output path
            method2_output_path = output_path + ".method2"
            with open(method2_output_path, 'wb') as alt_output_file:
                new_writer.write(alt_output_file)
            
            # If successful, use this as our output
            if os.path.exists(method2_output_path) and os.path.getsize(method2_output_path) > 0:
                # Verify it's not encrypted
                try:
                    check_reader = PdfReader(method2_output_path)
                    if not check_reader.is_encrypted:
                        # Success! Replace the output file
                        os.replace(method2_output_path, output_path)
                        # Clean up any remaining temp files
                        _cleanup_temp_files(temp_files)
                        return {"status": "success", "message": "PDF unlocked successfully"}
                except Exception as verify_error:
                    app.logger.error(f"Second approach verification error: {str(verify_error)}")
        except Exception as method2_error:
            app.logger.error(f"Second approach error: {str(method2_error)}")
        
        # RENDER-SPECIFIC APPROACH: Use a simplified approach for Render environment
        if IS_RENDER:
            tried_methods.append("render_specific")
            app.logger.info("Trying Render-specific approach")
            
            try:
                # More direct approach for Render - sometimes the environment needs simpler methods
                render_output_path = output_path + ".render"
                
                try:
                    # Open PDF with password
                    if password:
                        # Try with multiple encodings for Render environment
                        try_passwords = [
                            password, 
                            password.encode('utf-8').decode('utf-8'),
                            password.encode('ascii', errors='replace').decode('ascii')
                        ]
                        
                        success = False
                        render_reader = None
                        for pwd in try_passwords:
                            try:
                                render_reader = PdfReader(input_path, password=pwd)
                                if render_reader.is_encrypted:
                                    render_reader.decrypt(pwd)
                                if not render_reader.is_encrypted:
                                    success = True
                                    app.logger.info(f"Password worked on Render")
                                    break
                            except Exception as pwd_error:
                                app.logger.warning(f"Password attempt failed on Render: {str(pwd_error)}")
                                continue
                        
                        if not success:
                            app.logger.error("All password attempts failed on Render")
                            return {"status": "error", "message": "Incorrect password (Render)"}
                    else:
                        render_reader = reader
                    
                    # Create a simple writer
                    render_writer = PdfWriter()
                    
                    # Copy all pages directly
                    for page in render_reader.pages:
                        render_writer.add_page(page)
                        
                    # Write to output without any encryption calls at all
                    with open(render_output_path, 'wb') as f:
                        render_writer.write(f)
                    
                    # If file exists and has content, use it
                    if os.path.exists(render_output_path) and os.path.getsize(render_output_path) > 0:
                        os.replace(render_output_path, output_path)
                        _cleanup_temp_files(temp_files)
                        return {"status": "success", "message": "PDF unlocked successfully (Render)"}
                
                except Exception as render_inner_error:
                    app.logger.error(f"Render approach inner error: {str(render_inner_error)}")
            
            except Exception as render_error:
                app.logger.error(f"Render approach error: {str(render_error)}")
        
        # APPROACH 3: Try using a different encryption method
        tried_methods.append("alternative_encryption")
        app.logger.info("Trying third approach: Using alternative encryption approach")
        
        try:
            # Re-open the original PDF with password
            if password:
                reader3 = PdfReader(input_path, password=password)
                if reader3.is_encrypted:
                    reader3.decrypt(password)
            else:
                reader3 = PdfReader(input_path)
                
            # Create a new writer
            writer3 = PdfWriter()
            
            # Add each page to the writer
            for page in reader3.pages:
                writer3.add_page(page)
            
            # Set an empty user password and owner password explicitly
            # This should effectively remove protection while still creating a valid PDF
            writer3.encrypt('', '', use_128bit=True)
            
            # Remove the encryption to create a fully unlocked PDF
            writer3._encrypt = None
            
            # Write the output
            method3_output_path = output_path + ".method3"
            with open(method3_output_path, 'wb') as output_file:
                writer3.write(output_file)
            
            # Verify it worked
            if os.path.exists(method3_output_path) and os.path.getsize(method3_output_path) > 0:
                # Check if it's not encrypted
                try:
                    check_reader = PdfReader(method3_output_path)
                    if not check_reader.is_encrypted:
                        # Success! Replace the output file
                        os.replace(method3_output_path, output_path)
                        # Clean up any remaining temp files
                        _cleanup_temp_files(temp_files)
                        return {"status": "success", "message": "PDF unlocked successfully"}
                except Exception as verify_error:
                    app.logger.error(f"Third approach verification error: {str(verify_error)}")
        except Exception as method3_error:
            app.logger.error(f"Third approach error: {str(method3_error)}")

        # APPROACH 4: Specifically target owner password protection
        tried_methods.append("owner_password_removal")
        app.logger.info("Trying fourth approach: Owner password removal technique")
        
        try:
            # Try to open the PDF with an empty string as password - sometimes works for owner password
            try:
                reader4 = PdfReader(input_path, password='')
            except:
                # If that fails, try with the provided password
                if password:
                    reader4 = PdfReader(input_path, password=password)
                else:
                    # If no password was provided, re-use the original reader
                    reader4 = reader
            
            # Create a new PDF writer
            writer4 = PdfWriter()
            
            # Copy all the pages and their content
            for page in reader4.pages:
                writer4.add_page(page)
            
            # Transfer any document info (metadata) if it exists
            if hasattr(reader4, 'metadata') and reader4.metadata is not None:
                writer4.add_metadata(reader4.metadata)
            
            # Copy any document attachments
            if hasattr(reader4, 'attachments') and reader4.attachments:
                for attachment in reader4.attachments:
                    writer4.add_attachment(attachment['filename'], attachment['content'])
            
            # Write directly to a new file without encryption
            # Don't call encrypt() at all - just write without encryption
            method4_output_path = output_path + ".method4"
            with open(method4_output_path, 'wb') as output_file:
                # Use this direct write approach to skip any encryption logic
                writer4.write(output_file)
            
            # Verify the output file is valid and not encrypted
            if os.path.exists(method4_output_path) and os.path.getsize(method4_output_path) > 0:
                try:
                    verification_reader = PdfReader(method4_output_path)
                    if not verification_reader.is_encrypted:
                        # Success! Replace the output file
                        os.replace(method4_output_path, output_path)
                        # Clean up temporary files
                        _cleanup_temp_files(temp_files)
                        return {"status": "success", "message": "PDF unlocked successfully"}
                except Exception as verify_error:
                    app.logger.error(f"Fourth approach verification error: {str(verify_error)}")
        except Exception as method4_error:
            app.logger.error(f"Fourth approach error: {str(method4_error)}")
            
        # Clean up temporary files before returning error
        _cleanup_temp_files(temp_files)
            
        # If we've reached here, all methods have failed
        return {
            "status": "error", 
            "message": "Failed to unlock PDF. The file may have strong encryption or requires a different password."
        }
    except Exception as e:
        # Clean up temporary files in case of exception
        _cleanup_temp_files(temp_files)
        
        app.logger.error(f"Unlock PDF general error: {str(e)}")
        return {"status": "error", "message": f"General error: {str(e)}"}

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
    # Check if this is a request for alternative approach
    alternative_approach = data.get('alternative_approach', False)
    # Check if this is a no-password attempt (for owner-password-only PDFs)
    no_password_attempt = data.get('no_password_attempt', False)
    # Check if ASCII mode was used (helps with special characters)
    ascii_mode = data.get('ascii_mode', False)
    
    # Enhanced logging for production debugging
    app.logger.info(f"Password submitted for file_id: {file_id}")
    app.logger.info(f"Password length: {len(password)}")
    app.logger.info(f"Password first/last char: {password[0] if password else ''}/{password[-1] if password else ''}")
    app.logger.info(f"ASCII mode: {ascii_mode}")
    
    # For ASCII mode, ensure proper encoding 
    if ascii_mode:
        app.logger.info("ASCII mode is enabled, ensuring clean password")
        # Additional safety processing for ASCII-mode passwords
        try:
            # Ensure it's pure ASCII to avoid encoding issues on the server
            password = password.encode('ascii', errors='replace').decode('ascii')
            app.logger.info(f"ASCII cleaned password length: {len(password)}")
        except Exception as e:
            app.logger.error(f"Error in ASCII cleaning: {str(e)}")
    
    try:
        # Construct the paths
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
        
        if not os.path.exists(input_path):
            app.logger.error(f"File not found: {input_path}")
            return jsonify({
                'status': 'error',
                'message': 'File not found or expired'
            }), 404
            
        # Generate a unique ID for the output file
        output_id = str(uuid.uuid4())
        output_filename = f"{output_id}.pdf"
        output_path = os.path.join(app.config['PROCESSED_FOLDER'], output_filename)
        
        # Special handling for attempting to unlock with empty password
        if no_password_attempt:
            app.logger.info(f"Attempting to unlock file {file_id} without password (owner-password only)")
            try:
                # Try to directly open and copy the PDF with an empty password
                try:
                    reader = PdfReader(input_path, password='')
                    writer = PdfWriter()
                    
                    # Copy all pages
                    for page in reader.pages:
                        writer.add_page(page)
                    
                    # Write without encryption
                    with open(output_path, 'wb') as f:
                        writer.write(f)
                    
                    # Check if successful
                    success = False
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        try:
                            check = PdfReader(output_path)
                            if not check.is_encrypted:
                                success = True
                        except:
                            pass
                    
                    if success:
                        # Get original filename
                        original_filename = protected_files.get(file_id, "document.pdf")
                        
                        # Process the file for download
                        cleaned_filename = clean_filename(original_filename)
                        prefixed_filename = f"unlocked_{cleaned_filename}"
                        display_filename = secure_filename(prefixed_filename)
                        
                        # Store mapping
                        processed_files[output_filename] = display_filename
                        save_processed_files()
                        
                        # Cleanup
                        if os.path.exists(input_path):
                            os.remove(input_path)
                        if file_id in protected_files:
                            del protected_files[file_id]
                        
                        return jsonify({
                            'status': 'success',
                            'filename': prefixed_filename,
                            'download_url': f'/download/{output_filename}'
                        })
                except Exception as e:
                    app.logger.warning(f"No-password direct attempt failed: {str(e)}")
                
                # If first attempt failed, try the regular unlock_pdf with empty password
                unlock_result = unlock_pdf(input_path, output_path, '')
                if unlock_result["status"] == "success":
                    # Get original filename
                    original_filename = protected_files.get(file_id, "document.pdf")
                    
                    # Process the file for download
                    cleaned_filename = clean_filename(original_filename)
                    prefixed_filename = f"unlocked_{cleaned_filename}"
                    display_filename = secure_filename(prefixed_filename)
                    
                    # Store mapping
                    processed_files[output_filename] = display_filename
                    save_processed_files()
                    
                    # Cleanup
                    if os.path.exists(input_path):
                        os.remove(input_path)
                    if file_id in protected_files:
                        del protected_files[file_id]
                    
                    return jsonify({
                        'status': 'success',
                        'filename': prefixed_filename,
                        'download_url': f'/download/{output_filename}'
                    })
                else:
                    return jsonify({
                        'status': 'error',
                        'message': 'This PDF requires a password to unlock.'
                    })
            except Exception as e:
                app.logger.error(f"No-password attempt error: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        
        # If this is an alternative approach request, try a more direct method
        if alternative_approach:
            app.logger.info(f"Using alternative direct approach for file {file_id}")
            
            try:
                # Get the original filename from protected_files dictionary
                original_filename = protected_files.get(file_id, "document.pdf")
                
                # Create a specialized writer to bypass encryption
                try:
                    # Try to open and decrypt the PDF
                    reader = PdfReader(input_path, password=password)
                    if reader.is_encrypted:
                        reader.decrypt(password)
                        
                    # Create a temporary file path
                    temp_output_path = output_path + ".direct"
                    
                    # Create a new writer 
                    writer = PdfWriter()
                    
                    # Add all pages to the writer
                    for page in reader.pages:
                        writer.add_page(page)
                    
                    # Directly write to the output file without any encrypt calls
                    with open(temp_output_path, 'wb') as f:
                        writer.write(f)
                    
                    # Check if the file was created and is valid
                    if os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 0:
                        # Move to the actual output path
                        os.replace(temp_output_path, output_path)
                        
                        # Prepare the filenames for download
                        cleaned_filename = clean_filename(original_filename)
                        prefixed_filename = f"unlocked_{cleaned_filename}"
                        display_filename = secure_filename(prefixed_filename)
                        
                        # Store in processed files
                        processed_files[output_filename] = display_filename
                        save_processed_files()
                        
                        # Cleanup
                        if os.path.exists(input_path):
                            os.remove(input_path)
                        if file_id in protected_files:
                            del protected_files[file_id]
                        
                        # Return success
                        return jsonify({
                            'status': 'success',
                            'filename': prefixed_filename,
                            'download_url': f'/download/{output_filename}'
                        })
                    else:
                        return jsonify({
                            'status': 'error',
                            'message': 'Failed to create unlocked PDF with alternative approach'
                        })
                        
                except Exception as direct_error:
                    app.logger.error(f"Direct approach error: {str(direct_error)}")
                    return jsonify({
                        'status': 'error',
                        'message': f'Alternative approach failed: {str(direct_error)}'
                    })
            except Exception as alt_error:
                app.logger.error(f"General alternative approach error: {str(alt_error)}")
                return jsonify({
                    'status': 'error',
                    'message': str(alt_error)
                })
        
        # Standard approach - use the unlock_pdf function
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