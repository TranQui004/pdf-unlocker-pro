/**
 * Donation Modal Implementation
 * Author: Just TTQ
 */

class DonateModal {
    constructor() {
        this.modalElement = null;
        this.activeMethod = null;
        this.qrContainer = null;
        this.copyButton = null;
        this.currentInfo = null;
        this.initialize();
    }

    initialize() {
        // Create modal DOM structure
        this.createModalDOM();
        
        // Add event listeners
        this.addEventListeners();
        
        // Append to body
        document.body.appendChild(this.modalElement);
    }

    createModalDOM() {
        // Create main modal container
        this.modalElement = document.createElement('div');
        this.modalElement.className = 'donate-modal';
        
        // Modal content
        const modalHTML = `
            <div class="donate-container">
                <div class="donate-decoration donate-decoration-1"></div>
                <div class="donate-decoration donate-decoration-2"></div>
                
                <div class="donate-header">
                    <h2 class="donate-title">Support This Project</h2>
                    <button class="donate-close" id="donateCloseBtn">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                
                <div class="donate-content">
                    <p class="donate-description">
                        Thank you for considering a donation! Your support helps keep this tool free and allows for continued development and improvements.
                    </p>
                    
                    <div class="donate-methods">
                        <div class="donate-method" data-method="paypal">
                            <div class="donate-method-icon">
                                <i class="fab fa-paypal"></i>
                            </div>
                            <div class="donate-method-name">PayPal</div>
                        </div>
                        
                        <div class="donate-method" data-method="momo">
                            <div class="donate-method-icon">
                                <i class="fas fa-mobile-alt"></i>
                            </div>
                            <div class="donate-method-name">MoMo</div>
                        </div>
                        
                        <div class="donate-method" data-method="vietcombank">
                            <div class="donate-method-icon">
                                <i class="fas fa-university"></i>
                            </div>
                            <div class="donate-method-name">Vietcombank</div>
                        </div>
                        
                        <div class="donate-method" data-method="github">
                            <div class="donate-method-icon">
                                <i class="fab fa-github"></i>
                            </div>
                            <div class="donate-method-name">GitHub</div>
                        </div>
                    </div>
                    
                    <div class="donate-qr-container" id="donateQrContainer">
                        <img src="" alt="QR Code" class="donate-qr-code" id="donateQrImage">
                        <h3 class="donate-qr-title" id="donateQrTitle">Payment Information</h3>
                        <div class="donate-qr-info" id="donateQrInfo"></div>
                        <button class="donate-copy-btn" id="donateCopyBtn">
                            <i class="fas fa-copy"></i> Copy Info
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        this.modalElement.innerHTML = modalHTML;
        
        // Store references to DOM elements
        this.qrContainer = this.modalElement.querySelector('#donateQrContainer');
        this.qrImage = this.modalElement.querySelector('#donateQrImage');
        this.qrTitle = this.modalElement.querySelector('#donateQrTitle');
        this.qrInfo = this.modalElement.querySelector('#donateQrInfo');
        this.copyButton = this.modalElement.querySelector('#donateCopyBtn');
    }

    addEventListeners() {
        // Close button event
        const closeBtn = this.modalElement.querySelector('#donateCloseBtn');
        closeBtn.addEventListener('click', () => this.hide());
        
        // Background click to close
        this.modalElement.addEventListener('click', (e) => {
            if (e.target === this.modalElement) {
                this.hide();
            }
        });
        
        // Payment method selection
        const methods = this.modalElement.querySelectorAll('.donate-method');
        methods.forEach(method => {
            method.addEventListener('click', () => {
                // Remove active class from all methods
                methods.forEach(m => m.classList.remove('active'));
                
                // Add active class to clicked method
                method.classList.add('active');
                
                // Update active method
                this.activeMethod = method.dataset.method;
                
                // Show payment details
                this.showPaymentDetails(this.activeMethod);
            });
        });
        
        // Copy button
        this.copyButton.addEventListener('click', () => {
            if (this.currentInfo) {
                navigator.clipboard.writeText(this.currentInfo)
                    .then(() => {
                        // Change button text temporarily
                        const originalText = this.copyButton.innerHTML;
                        this.copyButton.innerHTML = '<i class="fas fa-check"></i> Copied!';
                        
                        setTimeout(() => {
                            this.copyButton.innerHTML = originalText;
                        }, 2000);
                    })
                    .catch(err => {
                        console.error('Failed to copy: ', err);
                    });
            }
        });
    }

    showPaymentDetails(method) {
        if (!method) return;
        
        try {
            // Get encrypted payment info
            const encryptedInfo = window.PAYMENT_INFO[method];
            if (!encryptedInfo) {
                console.error(`No payment information found for method: ${method}`);
                return;
            }
            
            // Decrypt the information
            const info = window.decryptInfo(encryptedInfo);
            this.currentInfo = info;
            
            // Set QR code
            const qrUrl = window.getQRCodeUrl(method, info);
            this.qrImage.src = qrUrl;
            
            // Set title and info
            let title = '';
            switch(method) {
                case 'paypal':
                    title = 'PayPal Email';
                    break;
                case 'momo':
                    title = 'MoMo Number';
                    break;
                case 'vietcombank':
                    title = 'Bank Account';
                    break;
                case 'github':
                    title = 'GitHub Sponsor';
                    break;
                default:
                    title = 'Payment Information';
            }
            
            this.qrTitle.textContent = title;
            this.qrInfo.textContent = info;
            
            // Show QR container
            this.qrContainer.classList.add('show');
        } catch (error) {
            console.error('Error showing payment details:', error);
        }
    }

    show() {
        // Add show class to make visible
        this.modalElement.classList.add('show');
        
        // Set default selection
        const defaultMethod = this.modalElement.querySelector('.donate-method');
        if (defaultMethod) {
            defaultMethod.click();
        }
    }

    hide() {
        // Remove show class
        this.modalElement.classList.remove('show');
        
        // Reset QR container
        setTimeout(() => {
            this.qrContainer.classList.remove('show');
            this.activeMethod = null;
            
            // Clear active state from all methods
            const methods = this.modalElement.querySelectorAll('.donate-method');
            methods.forEach(m => m.classList.remove('active'));
        }, 300);
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Create donate modal instance
    const donateModal = new DonateModal();
    
    // Add click handler to donate button
    const donateBtn = document.getElementById('donateBtn');
    if (donateBtn) {
        donateBtn.addEventListener('click', (e) => {
            e.preventDefault();
            donateModal.show();
        });
    }

    // Set up social media links from encrypted information
    setupSocialLinks();
});

/**
 * Sets up social media links using encrypted information
 */
function setupSocialLinks() {
    try {
        // GitHub Link
        const githubLink = document.getElementById('githubLink');
        if (githubLink && window.PAYMENT_INFO && window.PAYMENT_INFO.github) {
            const githubUrl = window.decryptInfo(window.PAYMENT_INFO.github);
            githubLink.href = githubUrl;
            githubLink.target = "_blank";
            githubLink.rel = "noopener noreferrer";
        }
        
        // Twitter Link
        const twitterLink = document.getElementById('twitterLink');
        if (twitterLink && window.PAYMENT_INFO && window.PAYMENT_INFO.twitter) {
            const twitterUrl = window.decryptInfo(window.PAYMENT_INFO.twitter);
            twitterLink.href = twitterUrl;
            twitterLink.target = "_blank";
            twitterLink.rel = "noopener noreferrer";
        }
        
        // Email Link
        const emailLink = document.getElementById('emailLink');
        if (emailLink && window.PAYMENT_INFO && window.PAYMENT_INFO.email) {
            const email = window.decryptInfo(window.PAYMENT_INFO.email);
            emailLink.href = `mailto:${email}`;
        }
    } catch (error) {
        console.error('Error setting up social links:', error);
    }
}
