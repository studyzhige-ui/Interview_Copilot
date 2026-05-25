/* ESLint config for the frontend.
 *
 * Kept opinionated-but-light:
 *   - The typescript-eslint recommended rules
 *   - React Hooks rules (the only ones that actually catch bugs not
 *     covered by typecheck — rule-of-hooks + exhaustive-deps)
 *   - A small allowlist of project conventions (logger via
 *     console.debug only, prefer const, no-unused-vars handled by TS)
 *
 * Heavy formatter rules belong in Prettier; we intentionally don't ship
 * Prettier yet because the existing codebase isn't formatted to any
 * single style and a one-shot reformatting would obliterate git blame.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react-hooks'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  rules: {
    // ``console.debug`` is fine (used in chat.ts wire-format
    // forward-compat path); ``console.log`` left in production code
    // is almost always an accident.
    'no-console': ['warn', { allow: ['warn', 'error', 'debug', 'info'] }],
    // TypeScript already flags unused vars; the eslint rule's signal
    // is just noise. Default config allows underscore prefix to opt out.
    '@typescript-eslint/no-unused-vars': ['warn', {
      argsIgnorePattern: '^_',
      varsIgnorePattern: '^_',
    }],
    // We have a few legitimate ``any`` usages (axios error shapes,
    // wire-format unknown casts). Warning is enough to flag drift
    // without blocking the build.
    '@typescript-eslint/no-explicit-any': 'warn',
    // React-hooks rules. ``rules-of-hooks`` is non-negotiable —
    // breaking it produces undefined behaviour. ``exhaustive-deps``
    // and other suggestion-level rules from the v7 plugin are
    // demoted to warning: the existing codebase has many legitimate
    // ``// eslint-disable-next-line`` escape hatches and a number
    // of ``setState in effect`` sites that are intentional refresh
    // bumps (the v7 plugin is more aggressive than v4 was). Treating
    // those as blocking would require either a wholesale refactor
    // or scattering eslint-disable comments — both worse than just
    // surfacing warnings for new code to consider.
    'react-hooks/exhaustive-deps': 'warn',
    'react-hooks/rules-of-hooks': 'error',
    'react-hooks/set-state-in-effect': 'warn',
    'react-hooks/error-boundaries': 'warn',
    'react-hooks/refs': 'warn',
  },
  ignorePatterns: ['dist', 'node_modules', 'src/test/setup.ts', '*.config.*'],
};
