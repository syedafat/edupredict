(() => {
    const root = document.documentElement;
    const preferenceQuery = window.matchMedia?.('(prefers-color-scheme: dark)');
    const buttons = document.querySelectorAll('[data-theme-toggle]');
    let userPreference = readPreference();

    function readPreference() {
        try {
            const saved = window.localStorage.getItem('edupredict-theme');
            return saved === 'dark' || saved === 'light' ? saved : null;
        } catch (error) {
            return null;
        }
    }

    function applyTheme(theme) {
        const isDark = theme === 'dark';
        root.classList.toggle('dark', isDark);
        buttons.forEach((button) => {
            button.setAttribute('aria-pressed', String(isDark));
            const label = isDark ? 'Switch to light mode' : 'Switch to dark mode';
            button.setAttribute('aria-label', label);
            button.setAttribute('title', label);
            button.querySelector('[data-theme-icon="light"]')?.classList.toggle('hidden', isDark);
            button.querySelector('[data-theme-icon="dark"]')?.classList.toggle('hidden', !isDark);
        });
    }

    function applySystemPreference() {
        applyTheme(preferenceQuery?.matches ? 'dark' : 'light');
    }

    if (userPreference) {
        applyTheme(userPreference);
    } else {
        applySystemPreference();
    }

    buttons.forEach((button) => {
        button.addEventListener('click', () => {
            userPreference = root.classList.contains('dark') ? 'light' : 'dark';
            applyTheme(userPreference);
            try {
                window.localStorage.setItem('edupredict-theme', userPreference);
            } catch (error) {
                // The selected theme still applies for this page when storage is unavailable.
            }
        });
    });

    const handleSystemChange = () => {
        if (userPreference === null) applySystemPreference();
    };
    if (preferenceQuery?.addEventListener) {
        preferenceQuery.addEventListener('change', handleSystemChange);
    } else {
        preferenceQuery?.addListener?.(handleSystemChange);
    }

    window.addEventListener('storage', (event) => {
        if (event.key !== 'edupredict-theme') return;
        userPreference = event.newValue === 'dark' || event.newValue === 'light' ? event.newValue : null;
        if (userPreference) applyTheme(userPreference);
        else applySystemPreference();
    });
})();
