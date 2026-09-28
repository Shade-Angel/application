import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: { host: true },
  resolve: {
    alias: {
      '@': path.resolve(frontendRoot, 'src'),
    },
  },
});
