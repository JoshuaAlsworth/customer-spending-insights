import pluginVue from "eslint-plugin-vue";
import { defineConfig } from "eslint/config";
import tseslint from "@vue/eslint-config-typescript";

export default defineConfig([
  ...pluginVue.configs["flat/recommended"],
  ...tseslint(),
  { ignores: ["dist/**"] },
]);
