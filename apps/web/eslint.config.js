import pluginVue from "eslint-plugin-vue";
import { defineConfig } from "eslint/config";
import tseslint from "@vue/eslint-config-typescript";

export default defineConfig([
  ...pluginVue.configs["flat/recommended"],
  ...tseslint(),
  { ignores: ["dist/**"] },
  {
    // Prettier owns template layout; retain Vue correctness rules.
    rules: {
      "vue/max-attributes-per-line": "off",
      "vue/singleline-html-element-content-newline": "off",
      "vue/html-indent": "off",
      "vue/html-closing-bracket-newline": "off",
      "vue/html-self-closing": "off",
    },
  },
]);
