/**
 * Payment Information Module
 * 
 * WARNING: The payment information in this file is encrypted.
 * DO NOT modify these values unless you know what you are doing.
 */

// Encrypted payment information
// These values are Base64 encoded - the actual information is not 
// directly accessible in the source code for security reasons
const PAYMENT_INFO = {
    // PayPal donation email
    paypal: "ZXhhbXBsZUBnbWFpbC5jb20=",
    
    // GitHub sponsor URL
    github: "aHR0cHM6Ly9naXRodWIuY29tL3Nwb25zb3JzL2p1c3R0dHE=",
    
    // Twitter profile
    twitter: "aHR0cHM6Ly90d2l0dGVyLmNvbS9qdXN0dHRx",
    
    // MoMo number
    momo: "MDk4NzY1NDMyMQ==",
    
    // Email address
    email: "anVzdHR0cUBnbWFpbC5jb20=",
    
    // Vietcombank account
    vietcombank: "MTIzNDU2Nzg5MCBWaWV0Y29tYmFuayBOZ3V5ZW4gVmFuIEE="
};

// Make available globally
window.PAYMENT_INFO = PAYMENT_INFO;

/**
 * Decrypts the payment information
 * @param {string} encryptedInfo - Base64 encoded string
 * @returns {string} Decoded information
 */
function decryptInfo(encryptedInfo) {
    try {
        // This is a simple Base64 decoding
        // In a real-world scenario, you might want to use more sophisticated encryption
        return atob(encryptedInfo);
    } catch (error) {
        console.error('Error decrypting information:', error);
        return 'Unable to decrypt information';
    }
}

// Make decryptInfo available globally
window.decryptInfo = decryptInfo;

/**
 * Generates QR code URL for payment info
 * @param {string} method - Payment method
 * @param {string} text - Text to encode in QR
 * @returns {string} QR code image URL
 */
function getQRCodeUrl(method, text) {
    // Use Google Charts API to generate QR code
    // This is a simple and reliable way to generate QR codes without additional libraries
    const baseUrl = 'https://chart.googleapis.com/chart?cht=qr&chs=200x200&chld=M|0&choe=UTF-8';
    
    // Different handling for different payment methods
    let qrContent = text;
    
    switch(method) {
        case 'paypal':
            qrContent = `https://www.paypal.com/paypalme/${text.replace('@gmail.com', '')}`;
            break;
        case 'github':
            qrContent = text; // Already a URL
            break;
        case 'momo':
            // MoMo deep link format (simplified)
            qrContent = `momo://app?action=transfer&phone=${text}`;
            break;
        case 'vietcombank':
            // Just use the account number, no special formatting
            qrContent = text;
            break;
        default:
            qrContent = text;
    }
    
    // Encode the content for URL
    const encodedContent = encodeURIComponent(qrContent);
    
    // Return the complete URL
    return `${baseUrl}&chl=${encodedContent}`;
}

// Make getQRCodeUrl available globally
window.getQRCodeUrl = getQRCodeUrl;
