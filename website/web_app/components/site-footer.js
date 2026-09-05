(function () {
    class SiteFooter extends HTMLElement {
        connectedCallback() {
            if (this.shadowRoot) return;
            const root = this.attachShadow({ mode: 'open' });
            root.innerHTML = `
                <style>
                    :host { display: block; }
                    .footer {
                        margin-top: 32px;
                        padding: 20px 24px;
                        color: #687785;
                        background: #f4f6f8;
                        border-top: 1px solid rgba(31, 51, 69, 0.12);
                        font-family: "Roboto Flex", Roboto, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                        font-size: 0.78rem;
                        text-align: center;
                    }
                    .footer p { margin: 0; }
                </style>
                <footer class="footer">
                    <p>GenePathwayAI. Pathway analysis for research use.</p>
                </footer>`;
        }
    }

    if (!customElements.get('site-footer')) {
        customElements.define('site-footer', SiteFooter);
    }
})();
