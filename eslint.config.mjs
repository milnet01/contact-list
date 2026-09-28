// ESLint for the browser script (CL-0077). Development-only: nothing here ships.
import js from "@eslint/js";
import globals from "globals";

export default [
    js.configs.recommended,
    {
        files: ["static/**/*.js"],
        languageOptions: {
            ecmaVersion: 2022,
            // app.js is a classic <script>, not a module.
            sourceType: "script",
            globals: globals.browser,
        },
        rules: {
            // Every top-level IIFE opts into strict mode itself.
            strict: ["error", "function"],
        },
    },
];
