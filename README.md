# PDF Unlocker Pro

A professional web application to unlock secured PDF files and remove restrictions like copy, edit, and print limitations.

![PDF Unlocker Pro](https://via.placeholder.com/800x400?text=PDF+Unlocker+Pro)

## Features

- Modern, responsive UI with professional design
- Drag and drop interface with animations for easy file upload
- Upload progress indicators and notifications
- Support for multiple PDF files (batch processing)
- Removes PDF restrictions (copy, edit, print)
- Removes "(SECURED)" and similar labels from filenames
- File size validation and error handling
- Comprehensive FAQ section
- Fully responsive design (mobile and desktop friendly)

## Requirements

- Python 3.7 or higher
- Flask
- PyPDF2
- Other dependencies listed in requirements.txt

## Installation

1. Clone this repository
2. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Start the application:
   ```bash
   python app.py
   ```
2. Open your web browser and navigate to `http://localhost:5000`
3. Drag and drop your PDF files or click to select files
4. Click "Unlock PDFs" to process the files
5. Download the unlocked PDFs with clean filenames (no "SECURED" indicators)

## How It Works

This application:
1. Uses PyPDF2 to remove encryption and restrictions from PDF files
2. Cleans filenames by removing indicators like "(SECURED)", "[PROTECTED]", etc.
3. Returns downloadable, unrestricted PDFs with clean filenames
4. Processes files locally (your files are never sent to external servers)

## Features in Detail

### User Interface
- Professional gradient design
- Animated file uploads and transitions
- Interactive hover effects
- Progress indicators during processing
- Toast notifications for success/error messages

### PDF Processing
- Removes all types of security restrictions
- Batch processing of multiple files
- Automatic cleaning of filenames
- Secure local processing

## Security Note

This tool is intended for legitimate use only. Please ensure you have the right to modify the PDF files you process. All processing is done locally on your machine - your files are never uploaded to any server.

## Disclaimer

PDF Unlocker Pro is designed to help users remove restrictions from PDF files they have legitimate access to. Users must ensure they have the legal right to modify PDF files before using this tool. We do not endorse or encourage the unauthorized modification of protected documents.

This tool is provided "as is" without warranty of any kind, express or implied. In no event shall the authors or copyright holders be liable for any claim, damages, or other liability arising from the use or in connection with this software.

By using PDF Unlocker Pro, you acknowledge that you are solely responsible for complying with applicable laws regarding document modification, copyright, and intellectual property rights.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

&copy; 2025 PDF Unlocker Pro 