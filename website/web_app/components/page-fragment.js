(() => {
    'use strict';

    window.definePageFragment = (name, markup) => {
        if (customElements.get(name)) return;
        customElements.define(name, class extends HTMLElement {
            connectedCallback() {
                const template = document.createElement('template');
                template.innerHTML = markup.trim();
                this.replaceWith(template.content.cloneNode(true));
            }
        });
    };
})();

