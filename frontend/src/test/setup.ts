// Test setup — runs once before every test file.
//
// Imports the @testing-library/jest-dom matchers so DOM assertions
// (toBeInTheDocument, toHaveTextContent, etc.) are available on
// vitest's ``expect``. The /vitest subpath ensures the matchers
// register on vitest's expect rather than jest's.
import '@testing-library/jest-dom/vitest';
