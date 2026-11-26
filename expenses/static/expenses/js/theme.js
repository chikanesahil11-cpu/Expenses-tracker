(() => {
    const storageKey = 'ledgerly-theme';
    const root = document.documentElement;

    // Sync localStorage if the server just saved a new theme preference in Settings
    const syncedTheme = root.dataset.syncTheme;
    if (syncedTheme === 'dark' || syncedTheme === 'light') {
        localStorage.setItem(storageKey, syncedTheme);
    }

    const savedTheme = localStorage.getItem(storageKey);
    const serverTheme = root.dataset.userTheme;
    const initialTheme = savedTheme || serverTheme || 'dark';

    const applyTheme = (theme) => {
        root.dataset.theme = theme;
        root.setAttribute('data-bs-theme', theme);

        document.querySelectorAll('[data-theme-toggle]').forEach(button => {
            const label = button.querySelector('span');
            if (label) {
                label.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
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
            const nextTheme = root.dataset.theme === 'dark' ? 'light' : 'dark';
            localStorage.setItem(storageKey, nextTheme);
            applyTheme(nextTheme);
        });
    });
})();
