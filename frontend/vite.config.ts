import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export default defineConfig({ plugins:[react() as any], server:{port:5173,proxy:{'/api':'http://127.0.0.1:8000'}}, test:{environment:'jsdom',setupFiles:['./src/setupTests.ts'],css:false} });
