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
    paypal: "aHR0cHM6Ly93d3cucGF5cGFsLmNvbS9wYXlwYWxtZS90cmFucXVpMDA0",
    
    // GitHub sponsor URL
    github: "aHR0cHM6Ly9naXRodWIuY29tL3Nwb25zb3JzL2p1c3R0dHE=",
    
    // Twitter profile
    twitter: "aHR0cHM6Ly94LmNvbS9UcmFuUXVpMDA0",
    
    // MoMo number
    momo: "MDc5NjA4NjM3Mg==",
    
    // Email address
    email: "dHF1aTI2N0BnbWFpbC5jb20=",
    
    // Vietcombank account
    vietcombank: "VFJBTiBUUk9ORyBRVUkgLSAxMDMxNDY5OTM4"
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
 * Returns the path to the QR code image based on the payment method
 * @param {string} method - Payment method
 * @returns {string} Path to the QR code image
 */
function getQRImagePath(method) {
    // Return the appropriate QR code image path based on the method
    switch(method) {
        case 'paypal':
            return '/static/qr_code/qr_paypal.png';
        case 'twitter':
            return '/static/qr_code/qr_twitter.png';
        case 'momo':
            return '/static/qr_code/qr_momo.jpg';
        case 'vietcombank':
            return '/static/qr_code/qr_vietcombank.jpg';
        default:
            return '';
    }
}

// Make getQRImagePath available globally
window.getQRImagePath = getQRImagePath;
