export default [
  {
    files: ["site/assets/*.js", "tests/web/*.mjs"],
    languageOptions: { ecmaVersion: 2022, sourceType: "module" },
    rules: {
      "no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
      "no-constant-condition": "error",
      "no-debugger": "error",
      "no-duplicate-case": "error",
      "no-dupe-keys": "error",
      "no-unreachable": "error",
      eqeqeq: "error",
    },
  },
];
