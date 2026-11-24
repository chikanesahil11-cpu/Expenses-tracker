
(() => {
    const storageKey = 'ledgerly-theme';

    // Midnight Emerald is the default theme
    const savedTheme = localStorage.getItem(storageKey);
    const initialTheme = savedTheme || 'dark';

    const applyTheme = (theme) => {
        document.documentElement.dataset.theme = theme;
        document.documentElement.setAttribute('data-bs-theme', theme);

        document.querySelectorAll('[data-theme-toggle]').forEach(button => {
            const label = button.querySelector('span');

            if (label) {
                label.textContent = theme === 'dark'
                    ? 'Light mode'
                    : 'Dark mode';
            }

            button.setAttribute(
                'aria-label',
                theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
            );
        });
    };

    applyTheme(initialTheme);

    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
        button.addEventListener('click', () => {
            const currentTheme = document.documentElement.dataset.theme;

            const nextTheme = currentTheme === 'dark'
                ? 'light'
                : 'dark';

            localStorage.setItem(storageKey, nextTheme);
            applyTheme(nextTheme);
        });
    });
})();
