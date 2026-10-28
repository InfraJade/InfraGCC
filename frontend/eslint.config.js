import js from '@eslint/js';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      'dist',
      'coverage',
      'node_modules',
      'playwright-report',
      'test-results',
      'public/config.js',
      'src/api/schema.d.ts',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser },
      parserOptions: {
        projectService: {
          allowDefaultProject: [
            'eslint.config.js',
            'postcss.config.js',
            'vite.config.ts',
            'tailwind.config.ts',
            'playwright.config.ts',
            'e2e/*.ts',
          ],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks, 'jsx-a11y': jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/consistent-type-imports': ['error', { fixStyle: 'inline-type-imports' }],
      '@typescript-eslint/no-misused-promises': ['error', { checksVoidReturn: { attributes: false } }],
      // Focus-trapped dialogs move focus on purpose.
      'jsx-a11y/no-autofocus': 'off',
      // `role` props on our own components (RequireRole) are app roles, not ARIA roles.
      'jsx-a11y/aria-role': ['error', { ignoreNonDOM: true }],
    },
  },
  {
    files: ['tests/**/*.{ts,tsx}', 'e2e/**/*.ts'],
    rules: {
      '@typescript-eslint/no-unsafe-assignment': 'off',
      '@typescript-eslint/no-unsafe-member-access': 'off',
      '@typescript-eslint/no-unsafe-call': 'off',
      '@typescript-eslint/no-unsafe-argument': 'off',
      '@typescript-eslint/unbound-method': 'off',
      '@typescript-eslint/require-await': 'off',
    },
  },
  {
    files: ['**/*.js'],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: { globals: { ...globals.node } },
  },
);
