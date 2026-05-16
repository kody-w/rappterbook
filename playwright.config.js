// @ts-check
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/playwright',
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: 'https://kody-w.github.io/rappterbook/',
    headless: true,
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
