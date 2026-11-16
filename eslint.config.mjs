// ESLint for the page's scripts and the browser tests: `npm run lint` (CI's lint job).
// The page's scripts are classic scripts (no modules, no build step) that share one
// global, AIPT, and must run on the oldest browsers the school labs and phones have
// (context/design-system.md §6: Chrome 109, iOS 15, Firefox ESR 115): ES2021 syntax at most.
import js from '@eslint/js';
import globals from 'globals';

export default [
    {
        // Only the repository's own scripts: not a Python environment's packages (CI's lint job
        // makes .venv at the root, and some packages carry JavaScript), nor generated reports.
        ignores: [
            'node_modules/', '.venv/', 'venv/', 'env/', 'models/', 'design/', 'evaluation/',
            'test-results/', 'playwright-report/', 'blob-report/',
        ],
    },
    js.configs.recommended,
    {
        files: ['static/javascript/**/*.js'],
        languageOptions: {
            ecmaVersion: 2021,
            sourceType: 'script',
            globals: {
                ...globals.browser,
                AIPT: 'writable',
            },
        },
        rules: {
            'no-unused-vars': ['error', { args: 'none', caughtErrors: 'none' }],
            'no-implicit-globals': 'error',
            'no-var': 'error',
            'prefer-const': 'error',
            eqeqeq: ['error', 'always'],
            // One 'use strict' at the top of each file, which wraps itself in a function.
            strict: ['error', 'global'],
        },
    },
    {
        files: ['**/*.mjs'],
        languageOptions: {
            ecmaVersion: 'latest',
            sourceType: 'module',
            globals: globals.node,
        },
    },
    {
        // The browser tests hand functions to the page (page.evaluate, addInitScript),
        // which run there.
        files: ['e2e/**/*.mjs'],
        languageOptions: {
            globals: { ...globals.node, ...globals.browser },
        },
    },
];
